import unittest
from unittest.mock import patch
from spark_link.discovery import advertised_names, scan_new_devices, filter_known_candidates

class DiscoveryBootstrapTests(unittest.TestCase):
 def test_mdns_discovers_spark_without_any_connectx_address(self):
  text='+;enP7s7;IPv4;spark-d983\\032SSH;SSH Remote Terminal;local\n+;enP7s7;IPv4;printer;SSH Remote Terminal;local\n'
  self.assertEqual(advertised_names(text),{'spark-d983.local'})
 def test_duplicate_machine_id_does_not_hide_new_hardware(self):
  known=[{'online':True,'machine_id':'same','device_id':'first','interfaces':{}}]
  new={'id':'key','device':{'machine_id':'same','device_id':'third'}}
  self.assertEqual(filter_known_candidates([new],known),[new])
 def test_mdns_candidate_is_offered_when_ssh_login_is_not_yet_known(self):
  head={'id':'head','online':True,'local':True,'hostname':'spark-first','machine_id':'x','device_id':'first'}
  with patch('spark_link.discovery.warm_neighbors'),patch('spark_link.discovery.probe',return_value={'online':False}),patch('spark_link.discovery.bootstrap_candidates',return_value=[{'address':'192.168.1.30','hostname':'spark-d983.local','source':'mdns'}]),patch('spark_link.discovery.fingerprint',return_value={'key_id':'key','host_key':'192.168.1.30 ssh-ed25519 AAAA'}):
   found=scan_new_devices({'nodes':[head]},[head])
  self.assertEqual(len(found),1)
  self.assertEqual(found[0]['address'],'192.168.1.30')
  self.assertFalse(found[0]['authorized'])
 def test_management_address_is_preferred_over_an_unready_cluster_address(self):
  import socket
  from subprocess import CompletedProcess
  from spark_link.discovery import bootstrap_candidates
  head={'id':'head','local':True,'online':True,'hostname':'spark-first','management_ip':'192.168.1.2','management_prefixlen':24}
  advertised='+;enP7s7;IPv4;spark-d983\\032SSH;SSH Remote Terminal;local\n'
  addresses=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.100.34.2',22)),(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.168.1.30',22))]
  with patch('spark_link.discovery.subprocess.run',return_value=CompletedProcess([],0,advertised,'')),patch('spark_link.discovery.socket.getaddrinfo',return_value=addresses):
   found=bootstrap_candidates([head])
  self.assertEqual(found[0]['address'],'192.168.1.30')
  self.assertEqual({c['address'] for c in found},{'10.100.34.2','192.168.1.30'})
