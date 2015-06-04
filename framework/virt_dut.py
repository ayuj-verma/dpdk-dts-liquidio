# BSD LICENSE
#
# Copyright(c) 2010-2015 Intel Corporation. All rights reserved.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#   * Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in
#     the documentation and/or other materials provided with the
#     distribution.
#   * Neither the name of Intel Corporation nor the names of its
#     contributors may be used to endorse or promote products derived
#     from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
import re
import time
import dts
import settings
from config import PortConf
from settings import NICS, LOG_NAME_SEP
from ssh_connection import SSHConnection
from project_dpdk import DPDKdut
from dut import Dut
from net_device import NetDevice
from logger import getLogger


class VirtDut(DPDKdut):

    """
    A connection to the CRB under test.
    This class sends commands to the CRB and validates the responses. It is
    implemented using either ssh for linuxapp or the terminal server for
    baremetal.
    All operations are in fact delegated to an instance of either CRBLinuxApp
    or CRBBareMetal.
    """

    def __init__(self, crb, serializer, virttype, vm_name, suite):
        super(Dut, self).__init__(crb, serializer)
        self.vm_ip = self.get_ip_address()
        self.NAME = 'virtdut' + LOG_NAME_SEP + '%s' % self.vm_ip
        # load port config from suite cfg
        self.suite = suite
        self.logger = getLogger(self.NAME)
        self.logger.config_execution('vmdut')
        self.session = SSHConnection(self.vm_ip, self.NAME,
                                     self.get_password())
        self.session.init_log(self.logger)

        # if redirect ssh port, there's only one session enabled
        self.alt_session = SSHConnection(self.vm_ip, self.NAME + '_alt',
                                         self.get_password())
        self.alt_session.init_log(self.logger)

        self.number_of_cores = 0
        self.tester = None
        self.cores = []
        self.architecture = None
        self.ports_info = None
        self.ports_map = []
        self.virttype = virttype

    def close_sessions(self):
        if self.session:
            self.session.close()
        if self.alt_session:
            self.alt_session.close()

    def set_nic_type(self, nic_type):
        """
        Set CRB NICS ready to validated.
        """
        self.nic_type = nic_type
        # vm_dut config will load from vm configuration file

    def load_portconf(self):
        """
        Load port config for this virtual machine
        """
        return

    def set_target(self, target):
        """
        Set env variable, these have to be setup all the time. Some tests
        need to compile example apps by themselves and will fail otherwise.
        Set hugepage on DUT and install modules required by DPDK.
        Configure default ixgbe PMD function.
        """
        self.set_toolchain(target)

        # set env variable
        # These have to be setup all the time. Some tests need to compile
        # example apps by themselves and will fail otherwise.
        self.send_expect("export RTE_TARGET=" + target, "#")
        self.send_expect("export RTE_SDK=`pwd`", "#")

        if not self.skip_setup:
            self.build_install_dpdk(target)

        self.setup_memory(hugepages=512)
        self.setup_modules(target)

        self.bind_interfaces_linux('igb_uio')

    def prerequisites(self, pkgName, patch):
        """
        Prerequest function should be called before execute any test case.
        Will call function to scan all lcore's information which on DUT.
        Then call pci scan function to collect nic device information.
        At last setup DUT' environment for validation.
        """
        if not self.skip_setup:
            self.prepare_package(pkgName, patch)

        self.send_expect("cd %s" % self.base_dir, "# ")
        self.send_expect("alias ls='ls --color=none'", "#")

        if self.get_os_type() == 'freebsd':
            self.send_expect('alias make=gmake', '# ')
            self.send_expect('alias sed=gsed', '# ')

        self.init_core_list()
        self.pci_devices_information()

        # scan ports before restore interface
        self.scan_ports()
        # restore dut ports to kernel
        if self.virttype != 'XEN':
            self.restore_interfaces()
        else:
            self.restore_interfaces_domu()
        # rescan ports after interface up
        self.rescan_ports()

        # no need to rescan ports for guest os just bootup
        # load port infor from config file
        self.load_portconf()

        # enable tester port ipv6
        self.host_dut.enable_tester_ipv6()
        self.mount_procfs()
        # auto detect network topology
        self.map_available_ports()
        # disable tester port ipv6
        self.host_dut.disable_tester_ipv6()

        # print latest ports_info
        for port_info in self.ports_info:
            self.logger.info(port_info)

    def restore_interfaces_domu(self):
        """
        Restore Linux interfaces.
        """
        for port in self.ports_info:
            pci_bus = port['pci']
            pci_id = port['type']
            driver = settings.get_nic_driver(pci_id)
            if driver is not None:
                addr_array = pci_bus.split(':')
                bus_id = addr_array[0]
                devfun_id = addr_array[1]
                port = NetDevice(self, bus_id, devfun_id)
                itf = port.get_interface_name()
                self.send_expect("ifconfig %s up" % itf, "# ")
                time.sleep(30)
                print self.send_expect("ip link ls %s" % itf, "# ")
            else:
                self.logger.info(
                    "NOT FOUND DRIVER FOR PORT (%s|%s)!!!" % (pci_bus, pci_id))

    def pci_devices_information(self):
        self.pci_devices_information_uncached()

    def get_memory_channels(self):
        """
        Virtual machine has no memory channel concept, so always return 1
        """
        return 1

    def check_ports_available(self, pci_bus, pci_id):
        """
        Check that whether auto scanned ports ready to use
        """
        pci_addr = "%s:%s" % (pci_bus, pci_id)
        if pci_id == "8086:100e":
            return False
        return True
        # load vm port conf need another function
        # need add vitrual function device into NICS

    def scan_ports(self):
        """
        Scan ports information, for vm will always scan
        """
        self.scan_ports_uncached()

    def scan_ports_uncached(self):
        """
        Scan ports and collect port's pci id, mac adress, ipv6 address.
        """
        scan_ports_uncached = getattr(
            self, 'scan_ports_uncached_%s' % self.get_os_type())
        return scan_ports_uncached()

    def map_available_ports(self):
        """
        Load or generate network connection mapping list.
        """
        self.map_available_ports_uncached()
        self.logger.warning("DUT PORT MAP: " + str(self.ports_map))

    def send_ping6(self, localPort, ipv6, mac=''):
        """
        Send ping6 packet from local port with destination ipv6 address.
        """
        if self.ports_info[localPort]['type'] == 'ixia':
            pass
        else:
            return self.send_expect("ping6 -w 1 -c 1 -A -I %s %s" % (self.ports_info[localPort]['intf'], ipv6), "# ", 10)
