#!/usr/bin/env python3

from __future__ import print_function

import sys
import time

from socket import error
from threading import Thread

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, QoSDurabilityPolicy

from rosbridge_library.capabilities.advertise import Advertise
from rosbridge_library.capabilities.publish import Publish
from rosbridge_library.capabilities.subscribe import Subscribe
from rosbridge_library.capabilities.advertise_service import AdvertiseService
from rosbridge_library.capabilities.unadvertise_service import UnadvertiseService
from rosbridge_library.capabilities.call_service import CallService

from rosbridge_client import RosbridgeWebSocketClient

# from twisted.python import log
from twisted.internet import reactor
from autobahn.twisted.websocket import WebSocketClientFactory

from twisted.internet.protocol import ReconnectingClientFactory    
from autobahn.twisted.websocket import WebSocketClientFactory, \
    WebSocketClientProtocol, \
    connectWS

# import diagnostic_updater
# class EchoClientProtocol(WebSocketClientProtocol):

#     def sendHello(self):
#         self.sendMessage("Hello, world!".encode('utf8'))

#     def onOpen(self):
#         self.sendHello()

#     def onMessage(self, payload, isBinary):
#         if not isBinary:
#             print("Text message received: {}".format(payload.decode('utf8')))
#         reactor.callLater(1, self.sendHello)
        
class RosbridgeWebsocketClientFactory(ReconnectingClientFactory, WebSocketClientFactory):

    node_handle = None   
    protocol = RosbridgeWebSocketClient

    # http://twistedmatrix.com/documents/current/api/twisted.internet.protocol.ReconnectingClientFactory.html
    # https://github.com/crossbario/autobahn-python/blob/master/examples/twisted/websocket/echo_variants/client_reconnecting.py

    maxDelay = 10
    maxRetries = 1000

    def startedConnecting(self, connector):
        cls = self.__class__       
        cls.node_handle.get_logger().info('Started to connect.')
       
    def clientConnectionLost(self, connector, reason):
        cls = self.__class__       
        cls.node_handle.get_logger().info('Lost connection. Reason: {}'.format(reason))
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        cls = self.__class__       
        cls.node_handle.get_logger().info('Connection failed. Reason: {}'.format(reason))
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)

class RosbridgeWebsocketClientNode(Node):
    def __init__(self):
        super().__init__('rosbridge_websocket_client')

        RosbridgeWebSocketClient.node_handle = self
        # RosbridgeWebSocketClient.updater = diagnostic_updater.Updater(self)
        RosbridgeWebsocketClientFactory.node_handle = self        

        ##################################################
        # Parameter handling                             #
        ##################################################
        retry_startup_delay = self.declare_parameter('retry_startup_delay', 2.0).value  # seconds.

        # RosbridgeWebSocket.use_compression = self.declare_parameter(
        #     'use_compression', False).value

        # get RosbridgeProtocol parameters
        RosbridgeWebSocketClient.fragment_timeout = self.declare_parameter(
            'fragment_timeout', RosbridgeWebSocketClient.fragment_timeout).value

        RosbridgeWebSocketClient.delay_between_messages = self.declare_parameter(
            'delay_between_messages', RosbridgeWebSocketClient.delay_between_messages).value

        RosbridgeWebSocketClient.max_message_size = self.declare_parameter(
            'max_message_size', RosbridgeWebSocketClient.max_message_size).value

        RosbridgeWebSocketClient.unregister_timeout = self.declare_parameter(
            'unregister_timeout', RosbridgeWebSocketClient.unregister_timeout).value

        bson_only_mode = self.declare_parameter('bson_only_mode', False).value

        if RosbridgeWebSocketClient.max_message_size == "None":
            RosbridgeWebSocketClient.max_message_size = None

        # SSL options
        certfile = self.declare_parameter('certfile').value
        keyfile = self.declare_parameter('keyfile').value
       
        # if authentication should be used
        RosbridgeWebSocketClient.authenticate = self.declare_parameter('authenticate', False).value

        port = self.declare_parameter('port', 1888).value
        address = self.declare_parameter('address', '').value
        domain = self.declare_parameter('domain', '').value
        robot_id = self.declare_parameter('robot_id', '').value
       
        # Publisher for number of connected clients
        # QoS profile with transient local durability (latched topic in ROS 1).
        client_count_qos_profile = QoSProfile(
            depth=10,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL
        )

        # Get the glob strings and parse them as arrays.
        topics_glob = self.declare_parameter('topics_glob', '').value

        services_glob = self.declare_parameter('services_glob', '').value

        params_glob = self.declare_parameter('params_glob', '').value

        RosbridgeWebSocketClient.topics_glob = [
            element.strip().strip("'")
            for element in topics_glob[1:-1].split(',')
            if len(element.strip().strip("'")) > 0]
        RosbridgeWebSocketClient.services_glob = [
            element.strip().strip("'")
            for element in services_glob[1:-1].split(',')
            if len(element.strip().strip("'")) > 0]
        RosbridgeWebSocketClient.params_glob = [
            element.strip().strip("'")
            for element in params_glob[1:-1].split(',')
            if len(element.strip().strip("'")) > 0]

        if "--port" in sys.argv:
            idx = sys.argv.index("--port")+1
            if idx < len(sys.argv):
                port = int(sys.argv[idx])
            else:
                print("--port argument provided without a value.")
                sys.exit(-1)

        if "--address" in sys.argv:
            idx = sys.argv.index("--address")+1
            if idx < len(sys.argv):
                address = int(sys.argv[idx])
            else:
                print("--address argument provided without a value.")
                sys.exit(-1)

        if "--retry_startup_delay" in sys.argv:
            idx = sys.argv.index("--retry_startup_delay") + 1
            if idx < len(sys.argv):
                retry_startup_delay = int(sys.argv[idx])
            else:
                print("--retry_startup_delay argument provided without a value.")
                sys.exit(-1)

        if "--fragment_timeout" in sys.argv:
            idx = sys.argv.index("--fragment_timeout") + 1
            if idx < len(sys.argv):
                RosbridgeWebSocketClient.fragment_timeout = int(sys.argv[idx])
            else:
                print("--fragment_timeout argument provided without a value.")
                sys.exit(-1)

        if "--delay_between_messages" in sys.argv:
            idx = sys.argv.index("--delay_between_messages") + 1
            if idx < len(sys.argv):
                RosbridgeWebSocketClient.delay_between_messages = float(sys.argv[idx])
            else:
                print("--delay_between_messages argument provided without a value.")
                sys.exit(-1)

        if "--max_message_size" in sys.argv:
            idx = sys.argv.index("--max_message_size") + 1
            if idx < len(sys.argv):
                value = sys.argv[idx]
                if value == "None":
                    RosbridgeWebSocketClient.max_message_size = None
                else:
                    RosbridgeWebSocketClient.max_message_size = int(value)
            else:
                print("--max_message_size argument provided without a value. (can be None or <Integer>)")
                sys.exit(-1)

        if "--unregister_timeout" in sys.argv:
            idx = sys.argv.index("--unregister_timeout") + 1
            if idx < len(sys.argv):
                unregister_timeout = float(sys.argv[idx])
            else:
                print("--unregister_timeout argument provided without a value.")
                sys.exit(-1)

        if "--topics_glob" in sys.argv:
            idx = sys.argv.index("--topics_glob") + 1
            if idx < len(sys.argv):
                value = sys.argv[idx]
                if value == "None":
                    RosbridgeWebSocketClient.topics_glob = []
                else:
                    RosbridgeWebSocketClient.topics_glob = [element.strip().strip("'") for element in value[1:-1].split(',')]
            else:
                print("--topics_glob argument provided without a value. (can be None or a list)")
                sys.exit(-1)

        if "--services_glob" in sys.argv:
            idx = sys.argv.index("--services_glob") + 1
            if idx < len(sys.argv):
                value = sys.argv[idx]
                if value == "None":
                    RosbridgeWebSocketClient.services_glob = []
                else:
                    RosbridgeWebSocketClient.services_glob = [element.strip().strip("'") for element in value[1:-1].split(',')]
            else:
                print("--services_glob argument provided without a value. (can be None or a list)")
                sys.exit(-1)

        if "--params_glob" in sys.argv:
            idx = sys.argv.index("--params_glob") + 1
            if idx < len(sys.argv):
                value = sys.argv[idx]
                if value == "None":
                    RosbridgeWebSocketClient.params_glob = []
                else:
                    RosbridgeWebSocketClient.params_glob = [element.strip().strip("'") for element in value[1:-1].split(',')]
            else:
                print("--params_glob argument provided without a value. (can be None or a list)")
                sys.exit(-1)

        if ("--bson_only_mode" in sys.argv) or bson_only_mode:
            RosbridgeWebSocketClient.bson_only_mode = bson_only_mode

        # if "--websocket_ping_interval" in sys.argv:
        #     idx = sys.argv.index("--websocket_ping_interval") + 1
        #     if idx < len(sys.argv):
        #         tornado_settings['websocket_ping_interval'] = float(sys.argv[idx])
        #     else:
        #         print("--websocket_ping_interval argument provided without a value.")
        #         sys.exit(-1)

        # if "--websocket_ping_timeout" in sys.argv:
        #     idx = sys.argv.index("--websocket_ping_timeout") + 1
        #     if idx < len(sys.argv):
        #         tornado_settings['websocket_ping_timeout'] = float(sys.argv[idx])
        #     else:
        #         print("--websocket_ping_timeout argument provided without a value.")
        #         sys.exit(-1)

        # To be able to access the list of topics and services, you must be able to access the rosapi services.
        if RosbridgeWebSocketClient.services_glob:
            RosbridgeWebSocketClient.services_glob.append("/rosapi/*")

        Subscribe.topics_glob = RosbridgeWebSocketClient.topics_glob
        Advertise.topics_glob = RosbridgeWebSocketClient.topics_glob
        Publish.topics_glob = RosbridgeWebSocketClient.topics_glob
        AdvertiseService.services_glob = RosbridgeWebSocketClient.services_glob
        UnadvertiseService.services_glob = RosbridgeWebSocketClient.services_glob
        CallService.services_glob = RosbridgeWebSocketClient.services_glob

        ##################################################
        # Done with parameter handling                   #
        ##################################################        
        server_address = 'ws://' + domain + ':' + str(port) + '/robot/'+robot_id #c0b5d7943d7b' #address + ':' + str(port)  #"ws://localhost:9090")      
        
        # factory = WebSocketClientFactory(server_address)        
        # factory.protocol = RosbridgeWebSocketClient  
        # reactor.connectTCP(domain, port, factory)
        # self.__thread = Thread(target=reactor.run, args=(False,))
        # self.__thread.start()

        factory = RosbridgeWebsocketClientFactory(server_address)
        connectWS(factory)      
        self.__thread = Thread(target=reactor.run, args=(False,))
        self.__thread.start()

    def __del__(self):        
        self.__thread.join()

def main(args=None):
    if args is None:
        args = sys.argv

    rclpy.init(args=args)
    rosbridge_websocket_client_node = RosbridgeWebsocketClientNode()
    # rate = rosbridge_websocket_client_node.create_rate(1000)
    
    try:
        while rclpy.ok():
            rclpy.spin_once(rosbridge_websocket_client_node, timeout_sec=0.01)
            # rclpy.spin_once(rosbridge_websocket_client_node) #, timeout_sec=0.01)
            # time.sleep(0.001)       
            # rclpy.spin(rosbridge_websocket_client_node)
    except KeyboardInterrupt:
        pass   
    
    rosbridge_websocket_client_node.destroy_node()
    rclpy.shutdown()
   

if __name__ == '__main__':
    main()

