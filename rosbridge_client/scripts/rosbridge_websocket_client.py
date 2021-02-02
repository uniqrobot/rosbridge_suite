#!/usr/bin/env python3
# Software License Agreement (BSD License)
#
# Copyright (c) 2012, Willow Garage, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from __future__ import print_function

import sys
import time

from socket import error

from threading import Thread
# from tornado.ioloop import IOLoop
# from tornado.ioloop import PeriodicCallback
# from tornado.web import Application

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, QoSDurabilityPolicy
from std_msgs.msg import Int32

# from rosbridge_server import RosbridgeWebSocket, ClientManager

from rosbridge_library.capabilities.advertise import Advertise
from rosbridge_library.capabilities.publish import Publish
from rosbridge_library.capabilities.subscribe import Subscribe
from rosbridge_library.capabilities.advertise_service import AdvertiseService
from rosbridge_library.capabilities.unadvertise_service import UnadvertiseService
from rosbridge_library.capabilities.call_service import CallService

from rosbridge_client import RosbridgeWebSocketClient

# def start_hook():
#     IOLoop.instance().start()

# def shutdown_hook():
#     IOLoop.instance().stop()


class RosbridgeWebsocketClientNode(Node):
    def __init__(self):
        super().__init__('rosbridge_websocket_client')

        RosbridgeWebSocketClient.node_handle = self

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

        port = self.declare_parameter('port', 9090).value

        address = self.declare_parameter('address', '').value

        # Publisher for number of connected clients
        # QoS profile with transient local durability (latched topic in ROS 1).
        client_count_qos_profile = QoSProfile(
            depth=10,
            durability=QoSDurabilityPolicy.RMW_QOS_POLICY_DURABILITY_TRANSIENT_LOCAL
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

        # application = Application([(r"/", RosbridgeWebSocketClient), (r"", RosbridgeWebSocketClient)], **tornado_settings)
        server_address = 'ws://www.uniqrobot.com:18888/robot/c0b5d7943d7b' #address + ':' + str(port)  #"ws://localhost:9090")

        connected = False
        ws = None
        while not connected and self.context.ok():
            try:
                if certfile is not None and keyfile is not None:
                    ws = RosbridgeWebSocketClient(
                    server_address,
                    ssl_options={
                        "certfile": certfile,
                        "keyfile": keyfile
                    })
                    ws.connect()
                else:
                    ws = RosbridgeWebSocketClient(server_address)
                    ws.open()
                    ws.connect()
                self.get_logger().info("Rosbridge WebSocket connected on {}".format(server_address))
                connected = True
            except error as e:
                self.get_logger().warn(
                    "Unable to access server: {} "
                    "Retrying in {}s.".format(e, retry_startup_delay))
                time.sleep(retry_startup_delay)
   
    def __del__(self):#当程序结束时运行
        ws.close()

def main(args=None):
    if args is None:
        args = sys.argv

    rclpy.init(args=args)
    rosbridge_websocket_client_node = RosbridgeWebsocketClientNode()

    # spin_callback = PeriodicCallback(lambda: rclpy.spin_once(rosbridge_websocket_node, timeout_sec=0.01), 1)
    # spin_callback.start()
    # start_hook()
    rate = rosbridge_websocket_client_node.create_rate(1)
    try:
        while rclpy.ok():
            rclpy.spin_once(rosbridge_websocket_client_node, timeout_sec=0.01)
            rate.sleep()
    except KeyboardInterrupt:
        pass

    rosbridge_websocket_client_node.destroy_node()
    rclpy.shutdown()
    # shutdown_hook()  # shutdown hook to stop the server

if __name__ == '__main__':
    main()
