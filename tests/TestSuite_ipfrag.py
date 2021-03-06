# BSD LICENSE
#
# Copyright(c) 2010-2014 Intel Corporation. All rights reserved.
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

"""
DPDK Test suite.
Test IPv4 fragmentation features in DPDK.
"""

import utils
import string
import re
import time
from settings import HEADER_SIZE
from packet import Packet, sniff_packets, load_sniff_packets

lpm_table_ipv4 = [
    "{IPv4(100,10,0,0), 16, P1}",
    "{IPv4(100,20,0,0), 16, P1}",
    "{IPv4(100,30,0,0), 16, P0}",
    "{IPv4(100,40,0,0), 16, P0}",
    "{IPv4(100,50,0,0), 16, P1}",
    "{IPv4(100,60,0,0), 16, P1}",
    "{IPv4(100,70,0,0), 16, P0}",
    "{IPv4(100,80,0,0), 16, P0}",
]

lpm_table_ipv6 = [
    "{{1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}, 48, P1}",
    "{{2,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}, 48, P1}",
    "{{3,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}, 48, P0}",
    "{{4,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}, 48, P0}",
    "{{5,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}, 48, P1}",
    "{{6,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}, 48, P1}",
    "{{7,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}, 48, P0}",
    "{{8,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1}, 48, P0}",
]

from test_case import TestCase


class TestIpfrag(TestCase):

    def portRepl(self, match):
        """
        Function to replace P([0123]) pattern in tables
        """

        portid = match.group(1)
        self.verify(int(portid) in range(4), "invalid port id")
        return '%s' % eval("P" + str(portid))

    def set_up_all(self):
        """
        ip_fragmentation Prerequisites
        """

        # Based on h/w type, choose how many ports to use
        ports = self.dut.get_ports()
        print ports

        # Verify that enough ports are available
        self.verify(len(ports) >= 2, "Insufficient ports for testing")

        self.ports_socket = self.dut.get_numa_id(ports[0])

        # Verify that enough threads are available
        cores = self.dut.get_core_list("2S/2C/2T")
        self.verify(cores is not None, "Insufficient cores for speed testing")

        global P0, P1
        P0 = ports[0]
        P1 = ports[1]

        pat = re.compile("P([0123])")

        # Prepare long prefix match table, replace P(x) port pattern
        lpmStr_ipv4 = "static struct l3fwd_ipv4_route \
l3fwd_ipv4_route_array[] = {\\\n"
        rtLpmTbl = list(lpm_table_ipv4)
        for idx in range(len(rtLpmTbl)):
            rtLpmTbl[idx] = pat.sub(self.portRepl, rtLpmTbl[idx])
            lpmStr_ipv4 = lpmStr_ipv4 + ' ' * 4 + rtLpmTbl[idx] + ",\\\n"
        lpmStr_ipv4 = lpmStr_ipv4 + "};"
        print lpmStr_ipv4
        lpmStr_ipv6 = "static struct l3fwd_ipv6_route l3fwd_ipv6_route_array[] = {\\\n"
        rtLpmTbl = list(lpm_table_ipv6)
        for idx in range(len(rtLpmTbl)):
            rtLpmTbl[idx] = pat.sub(self.portRepl, rtLpmTbl[idx])
            lpmStr_ipv6 = lpmStr_ipv6 + ' ' * 4 + rtLpmTbl[idx] + ",\\\n"
        lpmStr_ipv6 = lpmStr_ipv6 + "};"
        print lpmStr_ipv6
        self.dut.send_expect(r"sed -i '/l3fwd_ipv4_route_array\[\].*{/,/^\}\;/c\\%s' examples/ip_fragmentation/main.c" % lpmStr_ipv4, "# ")
        self.dut.send_expect(r"sed -i '/l3fwd_ipv6_route_array\[\].*{/,/^\}\;/c\\%s' examples/ip_fragmentation/main.c" % lpmStr_ipv6, "# ")
        # make application
        out = self.dut.build_dpdk_apps("examples/ip_fragmentation")
        self.verify("Error" not in out, "compilation error 1")
        self.verify("No such file" not in out, "compilation error 2")

        cores = self.dut.get_core_list("1S/1C/2T")
        coremask = utils.create_mask(cores)
        portmask = utils.create_mask([P0, P1])
        numPortThread = len([P0, P1]) / len(cores)
        result = True
        errString = ''

        # run ipv4_frag
        self.dut.send_expect("examples/ip_fragmentation/build/ip_fragmentation -c %s -n %d -- -p %s -q %s" % (
            coremask, self.dut.get_memory_channels(), portmask, numPortThread), "IP_FRAG:", 120)

        time.sleep(2)
        self.txItf = self.tester.get_interface(self.tester.get_local_port(P0))
        self.rxItf = self.tester.get_interface(self.tester.get_local_port(P1))
        self.dmac = self.dut.get_mac_address(P0)

    def functional_check_ipv4(self, pkt_sizes, burst=1, flag=None):
        """
        Perform functional fragmentation checks.
        """
        for size in pkt_sizes[::burst]:
            # simulate to set TG properties
            if flag == 'frag':
                # do fragment, each packet max length 1518 - 18 - 20 = 1480
                expPkts = (size - HEADER_SIZE['eth'] - HEADER_SIZE['ip']) / 1480
                if (size - HEADER_SIZE['eth'] - HEADER_SIZE['ip']) % 1480:
                    expPkts += 1
                val = 0
            elif flag == 'nofrag':
                expPkts = 0
                val = 2
            else:
                expPkts = 1
                val = 2

            inst = sniff_packets(intf=self.rxItf, timeout=5)
            # send packet
            for times in range(burst):
                pkt_size = pkt_sizes[pkt_sizes.index(size) + times]
                pkt = Packet(pkt_type='UDP', pkt_len=pkt_size)
                pkt.config_layer('ether', {'dst': self.dmac})
                pkt.config_layer('ipv4', {'dst': '100.10.0.1', 'src': '1.2.3.4', 'flags': val})
                pkt.send_pkt(tx_port=self.txItf)

            # verify normal packet just by number, verify fragment packet by all elements
            pkts = load_sniff_packets(inst)
            self.verify(len(pkts) == expPkts, "Failed on forward packet size " + str(size))
            if flag == 'frag':
                idx = 1
                for pkt in pkts:
                    # packet index should be same
                    pkt_id = pkt.strip_element_layer3("id")
                    if idx == 1:
                        prev_idx = pkt_id
                    self.verify(prev_idx == pkt_id, "Fragmented packets index not match")
                    prev_idx = pkt_id

                    # last flags should be 0
                    flags = pkt.strip_element_layer3("flags")
                    if idx == expPkts:
                        self.verify(flags == 0, "Fragmented last packet flags not match")
                    else:
                        self.verify(flags == 1, "Fragmented packets flags not match")

                    # fragment offset should be correct
                    frag = pkt.strip_element_layer3("frag")
                    self.verify((frag == ((idx - 1) * 185)), "Fragment packet frag not match")
                    idx += 1

    def functional_check_ipv6(self, pkt_sizes, burst=1, flag=None, funtion=None):
        """
        Perform functional fragmentation checks.
        """
        for size in pkt_sizes[::burst]:
            # simulate to set TG properties
            if flag == 'frag':
                # each packet max len: 1518 - 18 (eth) - 40 (ipv6) - 8 (ipv6 ext hdr) = 1452
                expPkts = (size - HEADER_SIZE['eth'] - HEADER_SIZE['ipv6']) / 1452
                if (size - HEADER_SIZE['eth'] - HEADER_SIZE['ipv6']) % 1452:
                    expPkts += 1
                val = 0
            else:
                expPkts = 1
                val = 2

            inst = sniff_packets(intf=self.rxItf, timeout=5)
            # send packet
            for times in range(burst):
                pkt_size = pkt_sizes[pkt_sizes.index(size) + times]
                pkt = Packet(pkt_type='IPv6_UDP', pkt_len=pkt_size)
                pkt.config_layer('ether', {'dst': self.dmac})
                pkt.config_layer('ipv6', {'dst': '101:101:101:101:101:101:101:101', 'src': 'ee80:ee80:ee80:ee80:ee80:ee80:ee80:ee80'})
                pkt.send_pkt(tx_port=self.txItf)

            # verify normal packet just by number, verify fragment packet by all elements
            pkts = load_sniff_packets(inst)
            self.verify(len(pkts) == expPkts, "Failed on forward packet size " + str(size))
            if flag == 'frag':
                idx = 1
                for pkt in pkts:
                    # packet index should be same
                    pkt_id = pkt.strip_element_layer4("id")
                    if idx == 1:
                        prev_idx = pkt_id
                    self.verify(prev_idx == pkt_id, "Fragmented packets index not match")
                    prev_idx = pkt_id

                    # last flags should be 0
                    flags = pkt.strip_element_layer4("m")
                    if idx == expPkts:
                        self.verify(flags == 0, "Fragmented last packet flags not match")
                    else:
                        self.verify(flags == 1, "Fragmented packets flags not match")

                    # fragment offset should be correct
                    frag = pkt.strip_element_layer4("offset")
                    self.verify((frag == int((idx - 1) * 181.5)), "Fragment packet frag not match")
                    idx += 1

    def set_up(self):
        """
        Run before each test case.
        """
        self.tester.send_expect("ifconfig %s mtu 9200" % self.tester.get_interface(self.tester.get_local_port(P0)), "#")
        self.tester.send_expect("ifconfig %s mtu 9200" % self.tester.get_interface(self.tester.get_local_port(P1)), "#")

    def test_ipfrag_normalfwd(self):
        """
        Normal forward with 64, 128, 256, 512, 1024, 1518.
        """

        sizelist = [64, 128, 256, 512, 1024, 1518]

        self.functional_check_ipv4(sizelist)
        self.functional_check_ipv6(sizelist)

    def test_ipfrag_nofragment(self):
        """
        Don't fragment test with 1519
        """

        sizelist = [1519]

        self.functional_check_ipv4(sizelist, 1, 'nofrag')

    def test_ipfrag_fragment(self):
        """
        Fragment test with more than 1519 packet sizes.
        """

        sizelist = [1519, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000]
        cores = self.dut.get_core_list("1S/1C/2T")

        self.functional_check_ipv4(sizelist, 1, 'frag')
        self.functional_check_ipv6(sizelist, 1, 'frag')

    def benchmark(self, index, lcore, num_pthreads, size_list):
        """
        Just Test IPv4 Throughput for selected parameters.
        """

        Bps = dict()
        Pps = dict()
        Pct = dict()

        if int(lcore[0]) == 1:
            core_mask = utils.create_mask(self.dut.get_core_list(lcore, socket=self.ports_socket))
        else:
            core_mask = utils.create_mask(self.dut.get_core_list(lcore))

        portmask = utils.create_mask([P0, P1])

        self.dut.send_expect("examples/ip_fragmentation/build/ip_fragmentation -c %s -n %d -- -p %s -q %s" % (
            core_mask, self.dut.get_memory_channels(), portmask, num_pthreads), "IP_FRAG:", 120)

        result = [2, lcore, num_pthreads]
        for size in size_list:
            dmac = self.dut.get_mac_address(P0)
            flows = ['Ether(dst="%s")/IP(src="1.2.3.4", dst="100.10.0.1", flags=0)/("X"*%d)' % (dmac, size - 38),
                     'Ether(dst="%s")/IP(src="1.2.3.4", dst="100.20.0.1", flags=0)/("X"*%d)' % (dmac, size - 38),
                     'Ether(dst="%s")/IPv6(dst="101:101:101:101:101:101:101:101",src="ee80:ee80:ee80:ee80:ee80:ee80:ee80:ee80")/Raw(load="X"*%d)' % (dmac, size - 58),
                     'Ether(dst="%s")/IPv6(dst="201:101:101:101:101:101:101:101",src="ee80:ee80:ee80:ee80:ee80:ee80:ee80:ee80")/Raw(load="X"*%d)' % (dmac, size - 58)]
            self.tester.scapy_append('wrpcap("test1.pcap", [%s])' % string.join(flows, ','))

            # reserved for rx/tx bidirection test
            dmac = self.dut.get_mac_address(P1)
            flows = ['Ether(dst="%s")/IP(src="1.2.3.4", dst="100.30.0.1", flags=0)/("X"*%d)' % (dmac, size - 38),
                     'Ether(dst="%s")/IP(src="1.2.3.4", dst="100.40.0.1", flags=0)/("X"*%d)' % (dmac, size - 38),
                     'Ether(dst="%s")/IPv6(dst="301:101:101:101:101:101:101:101",src="ee80:ee80:ee80:ee80:ee80:ee80:ee80:ee80")/Raw(load="X"*%d)' % (dmac, size - 58),
                     'Ether(dst="%s")/IPv6(dst="401:101:101:101:101:101:101:101",src="ee80:ee80:ee80:ee80:ee80:ee80:ee80:ee80")/Raw(load="X"*%d)' % (dmac, size - 58)]
            self.tester.scapy_append('wrpcap("test2.pcap", [%s])' % string.join(flows, ','))

            self.tester.scapy_execute()

            tgenInput = []
            tgenInput.append((self.tester.get_local_port(P0), self.tester.get_local_port(P1), "test1.pcap"))
            tgenInput.append((self.tester.get_local_port(P1), self.tester.get_local_port(P0), "test2.pcap"))

            factor = (size + 1517) / 1518
            # wireSpd = 2 * 10000.0 / ((20 + size) * 8)
            Bps[str(size)], Pps[str(size)] = self.tester.traffic_generator_throughput(tgenInput)
            self.verify(Pps[str(size)] > 0, "No traffic detected")
            Pps[str(size)] *= 1.0 / factor / 1000000
            Pct[str(size)] = (1.0 * Bps[str(size)] * 100) / (2 * 10000000000)

            result.append(Pps[str(size)])
            result.append(Pct[str(size)])

        self.result_table_add(result)

        self.dut.send_expect("^C", "#")

    def test_perf_ipfrag_throughtput(self):
        """
        Performance test for 64, 1518, 1519, 2k and 9k.
        """
        sizes = [64, 1518, 1519, 2000, 9000]

        tblheader = ["Ports", "S/C/T", "SW threads"]
        for size in sizes:
            tblheader.append("%dB Mpps" % size)
            tblheader.append("%d" % size)

        self.result_table_create(tblheader)

        lcores = [("1S/1C/1T", 2), ("1S/1C/2T", 2), ("1S/2C/1T", 2), ("2S/1C/1T", 2)]
        index = 1
        for (lcore, numThr) in lcores:
            self.benchmark(index, lcore, numThr, sizes)
            index += 1

        self.result_table_print()

    def tear_down(self):
        """
        Run after each test case.
        """
        self.tester.send_expect("ifconfig %s mtu 1500" % self.tester.get_interface(self.tester.get_local_port(P0)), "#")
        self.tester.send_expect("ifconfig %s mtu 1500" % self.tester.get_interface(self.tester.get_local_port(P1)), "#")

    def tear_down_all(self):
        """
        Run after each test suite.
        """
        self.dut.send_expect("^C", "#")
        pass
