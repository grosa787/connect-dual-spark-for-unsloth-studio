import unittest
from spark_link.multi import model_command

class MultiTests(unittest.TestCase):
    def test_two_available_workers_create_three_devices(self):
        command = model_command('/binary', ['-m', '/model.gguf', '--rpc', '192.168.1.2:1', '-c', '1048576'], ['10.100.32.2:50053', '10.100.34.2:50053'])
        self.assertEqual(command[command.index('--device')+1], 'CUDA0,RPC0,RPC1')
        self.assertNotIn('192.168.1.2:1', command)
        self.assertEqual(command[command.index('-c')+1], '1048576')
    def test_detached_third_uses_two_node_q8_split(self):
        command = model_command('/binary', ['-m', '/DeepSeek-V4-Flash-Vision-Exp-UD-Q8_K_XL-00001-of-00005.gguf'], ['10.100.32.2:50053'])
        self.assertEqual(command[command.index('--tensor-split')+1], '43,57')
        self.assertEqual(command[command.index('--rpc')+1], '10.100.32.2:50053')
