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

import uuid

from rclpy.time import Time
import time
# TODO(@jubeira): Re-add once rosauth is ported to ROS2.
# from rosauth.srv import Authentication

import sys
import threading
import traceback
from functools import partial, wraps

from rosbridge_library.rosbridge_protocol import RosbridgeProtocol
from rosbridge_library.util import json, bson

from autobahn.twisted.websocket import WebSocketClientProtocol, WebSocketClientFactory
    

def _log_exception():
    """Log the most recent exception to ROS."""
    exc = traceback.format_exception(*sys.exc_info())
    RosbridgeWebSocketClient.node_handle.get_logger().error(''.join(exc))


def log_exceptions(f):
    """Decorator for logging exceptions to ROS."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception:
            _log_exception()
            raise
    return wrapper


class RosbridgeWebSocketClient(WebSocketClientProtocol):
    client_id_seed = 1   
    # authenticate = False
    # use_compression = False

    # The following are passed on to RosbridgeProtocol
    # defragmentation.py:
    fragment_timeout = 600                  # seconds
    # protocol.py:
    delay_between_messages = 0              # seconds
    max_message_size = 10000000             # bytes
    unregister_timeout = 10.0               # seconds
    bson_only_mode = False
    node_handle = None
    # seed = 0


    @log_exceptions
    def __init__(self): #, timeout):   
        super().__init__()     
        cls = self.__class__
        parameters = {
            "fragment_timeout": cls.fragment_timeout,
            "delay_between_messages": cls.delay_between_messages,
            "max_message_size": cls.max_message_size,
            "unregister_timeout": cls.unregister_timeout,
            "bson_only_mode": cls.bson_only_mode
        }
        try:
            self.protocol = RosbridgeProtocol(cls.client_id_seed, cls.node_handle, parameters=parameters)
            self.protocol.outgoing = self.outgoing_message
            # self.set_nodelay(True)
            self.authenticated = False
            self._write_lock = threading.RLock()

        except Exception as exc:
            cls.node_handle.get_logger().error("Connect to server failed.  Reason: {}".format(exc))

        if cls.authenticate:
            cls.node_handle.get_logger().info("Awaiting proper authentication...")


    def onConnect(self, response):
        cls = self.__class__
        cls.node_handle.get_logger().info("websocket connected: {0}".format(response.peer))       

    def onConnecting(self, transport_details):
        cls = self.__class__
        cls.node_handle.get_logger().info("websocket connecting...: {}".format(transport_details))       
        return None 

    # def onOpen(self):
    #     cls = self.__class__
    #     print("WebSocket connection open.")

    #     def hello():
    #         self.sendMessage("Hello, world!".encode('utf8'))
    #         self.sendMessage(b"\x00\x01\x03\x04", isBinary=True)
    #         self.factory.reactor.callLater(1, hello)

    #     # start sending messages every second ..
    #     hello()

    def onMessage(self, payload, isBinary):
        cls = self.__class__
        if isBinary:
            cls.node_handle.get_logger().info("Received binary data: {0} bytes".format(len(payload)))          
        else:
            # print("Text message received: {0}".format(payload.decode('utf8')))
            cls.node_handle.get_logger().debug("websocket received: (%s)" % str(payload))
            self.protocol.incoming(payload.decode('utf8',"ignore"))

    def onClose(self, wasClean, code, reason):
        cls = self.__class__
        cls.node_handle.get_logger().info("websocket disconnected: {0} {1}".format(code, reason))  

    def outgoing_message(self, message):      
        cls = self.__class__     
        try:
            with self._write_lock:
                # if len(message) < 65536: 
                cls.node_handle.get_logger().debug("websocket sent: (%s)" % str(message))                                 
                self.sendMessage(message.encode('utf8',"ignore")) #.encode('utf8'))
        except Exception as e:
            cls.node_handle.get_logger().error('websocket error:%s' % str(e))
       
