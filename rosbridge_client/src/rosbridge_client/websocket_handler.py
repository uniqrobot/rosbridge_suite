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

# from tornado import version_info as tornado_version_info
# from tornado.ioloop import IOLoop
# from tornado.iostream import StreamClosedError
# from tornado.websocket import WebSocketHandler, WebSocketClosedError
# from tornado.gen import coroutine, BadYieldError

from rosbridge_library.rosbridge_protocol import RosbridgeProtocol
from rosbridge_library.util import json, bson

from std_msgs.msg import Int32

# from ws4py.client.threadedclient import WebSocketClient

# from ws4py.client.tornadoclient import TornadoWebSocketClient
# from tornado import ioloop

from tornado.ioloop import IOLoop, PeriodicCallback
from tornado import gen
from tornado.websocket import websocket_connect

import time
import functools
import json

from tornado import gen
from tornado import httpclient
from tornado import httputil
from tornado import ioloop
from tornado import websocket

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

APPLICATION_JSON = 'application/json'
DEFAULT_CONNECT_TIMEOUT = 30
DEFAULT_REQUEST_TIMEOUT = 30


class WebSocketClient(object):
    """Base for web socket clients.
    """

    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2

    def __init__(self, io_loop=None,
                 connect_timeout=DEFAULT_CONNECT_TIMEOUT,
                 request_timeout=DEFAULT_REQUEST_TIMEOUT):

        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self._io_loop = io_loop or ioloop.IOLoop.current()
        self._ws_connection = None
        self._connect_status = self.DISCONNECTED

    def connect(self, url):
        """Connect to the server.
        :param str url: server URL.
        """
        self._connect_status = self.CONNECTING
        headers = httputil.HTTPHeaders({'Content-Type': APPLICATION_JSON})
        request = httpclient.HTTPRequest(url=url,
                                         connect_timeout=self.connect_timeout,
                                         request_timeout=self.request_timeout,
                                         headers=headers)
        ws_conn = websocket.WebSocketClientConnection(self._io_loop, request)
        ws_conn.connect_future.add_done_callback(self._connect_callback)

    def send(self, data):
        """Send message to the server
        :param str data: message.
        """

        if self._ws_connection:
            self._ws_connection.write_message(json.dumps(data))

    def close(self, reason=''):
        """Close connection.
        """

        if self._connect_status != self.DISCONNECTED:
            self._connect_status = self.DISCONNECTED
            self._ws_connection and self._ws_connection.close()
            self._ws_connection = None
            self.on_connection_close(reason)

    def _connect_callback(self, future):
        if future.exception() is None:
            self._connect_status = self.CONNECTED
            self._ws_connection = future.result()
            self.on_connection_success()
            self._read_messages()
        else:
            self.close(future.exception())

    def is_connected(self):
        return self._ws_connection is not None

    @gen.coroutine
    def _read_messages(self):
        while True:
            msg = yield self._ws_connection.read_message()
            if msg is None:
                self.close()
                break

            self.on_message(msg)

    def on_message(self, msg):
        """This is called when new message is available from the server.
        :param str msg: server message.
        """

        pass

    def on_connection_success(self):
        """This is called on successful connection ot the server.
        """

        pass

    def on_connection_close(self, reason):
        """This is called when server closed the connection.
        """
        pass


class RosbridgeWebSocketClient(WebSocketClient):
    client_id_seed = 1
    # clients_connected = 0
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
    heartbeat_interval = 3


    @log_exceptions
    def __init__(self, io_loop=None,
                 connect_timeout=DEFAULT_CONNECT_TIMEOUT,
                 request_timeout=DEFAULT_REQUEST_TIMEOUT): #, timeout):
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
            # self.stream.max_buffer_size = 256 * 1024 * 1024
            # self.reading_buffer_size = 10000000
            # cls.client_id_seed += 1
            # cls.clients_connected += 1
            # self.client_id = uuid.uuid4()
            # if cls.client_manager:
                # cls.client_manager.add_client(self.client_id, self.request.remote_ip)
            # self.connect()
            # self.run_forever()
        except Exception as exc:
            cls.node_handle.get_logger().error("Connect to server failed.  Reason: {}".format(exc))

        # cls.node_handle.get_logger().info("Client connected")
        # cls.node_handle.get_logger().info("Client connected. {} clients total.".format(cls.clients_connected))
        if cls.authenticate:
            cls.node_handle.get_logger().info("Awaiting proper authentication...")

        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self._io_loop = io_loop or ioloop.IOLoop.current()
        self.ws_url = None
        self.auto_reconnet = False
        self.last_active_time = 0
        self.pending_hb = None

        super(RosbridgeWebSocketClient, self).__init__(self._io_loop,
                                                       self.connect_timeout,
                                                       self.request_timeout)

    def connect(self, url, auto_reconnet=True, reconnet_interval=10):
        self.ws_url = url
        self.auto_reconnet = auto_reconnet
        self.reconnect_interval = reconnet_interval

        super(RosbridgeWebSocketClient, self).connect(self.ws_url)       

    def send(self, msg):
        super(RosbridgeWebSocketClient, self).send(msg)
        self.last_active_time = time.time()

    def on_message(self, msg):
        # print'on_message msg=', msg
        self.last_active_time = time.time()
        self.protocol.incoming(str(msg))
    
    def on_connection_success(self):
        cls.node_handle.get_logger().info("connected")
        self.send(self.msg)
        self.last_active_time = time.time()
        self.send_heartbeat()

    def on_connection_close(self, reason):
        print('Connection closed reason=%s' % (reason,))
        self.pending_hb and self._io_loop.remove_timeout(self.pending_hb)

        self.reconnect()

    def reconnect(self):
        # print 'reconnect'
        if not self.is_connected() and self.auto_reconnet:
            self._io_loop.call_later(self.reconnect_interval,
                                     super(RosbridgeWebSocketClient, self).connect, self.ws_url)

    def send_heartbeat(self):
        if self.is_connected():
            now = time.time()
            if (now > self.last_active_time + self.heartbeat_interval):
                self.last_active_time = now
                self.send(self.hb_msg)

            self.pending_hb = self._io_loop.call_later(self.heartbeat_interval, self.send_heartbeat)
    # @gen.coroutine
    # def connect(self):
    #     cls = self.__class__
    #     cls.node_handle.get_logger().info("trying to connect")
    #     try:
    #         self.ws = yield websocket_connect(self.url)
    #     except Exception as e:
    #         cls.node_handle.get_logger().error("connection error")
    #     else:
    #         cls.node_handle.get_logger().info("connected")
    #         self.run()

    # @gen.coroutine
    # def run(self):
    #     cls = self.__class__
    #     while True:
    #         try:
    #             msg = yield self.ws.read_message()
    #         except Exception as e:
    #             cls.node_handle.get_logger().error('接收错误')
    #             cls.node_handle.get_logger().error(str(e))
    #         # if msg is None:
    #         #     cls.node_handle.get_logger().info("connection closed")
    #         #     self.ws = None
    #         #     self.protocol.finish()
    #         #     break
    #         # cls.node_handle.get_logger().info("Received: (%s)" % str(msg))
    #         self.protocol.incoming(str(msg))
    
    # def keep_alive(self):
    #     if self.ws is None:
    #         self.connect()
    #     else:
    #         self.ws.write_message("keep alive")

    # def received_message(self, message):
    #     """
    #     Process incoming from server
    #     """
    #     cls = self.__class__
    #     # cls.node_handle.get_logger().info("Received: (%s)" % str(message))
    #     # if type(message) is bytes:
    #     #     message = message.decode('utf-8')
    #     self.protocol.incoming(str(message))
   
    # @log_exceptions
    # def closed(self, code, reason=None):
    #     """
    #     Called by the server when the websocket stream and connection are
    #     finally closed
    #     """
    #     cls = self.__class__
    #     # rospy.loginfo("Closed")
    #     self.protocol.finish()
    #     # ioloop.IOLoop.instance().stop()
    #     cls.node_handle.get_logger().info("Closed. (%s, %s)" %( code, reason))
 
    def outgoing_message(self, message):
        # if type(message) == bson.BSON:
        #     binary = True
        # elif type(message) == bytearray:
        #     binary = True
        #     message = bytes(message)
        # else:
        #     binary = False

        cls = self.__class__
        # cls.node_handle.get_logger().info("Sent: (%s)" % str(message))
        # with self._write_lock:
            # if len(message) < 65536:   #消息大于65536会报错
        # print(time.asctime( time.localtime(time.time())))
        # print('---------------------------------------')
        # print(len(message))
        # print(message)
        # if len(message) > 65536:             
        #     return
            # print(message)
        try:
            # if len(message) > 65536:             
            #     return
            self.send(message)
        except Exception as e:
            cls.node_handle.get_logger().error('发送错误')
            cls.node_handle.get_logger().error(str(e))
        

        # with self._write_lock:
        #     IOLoop.instance().add_callback(partial(self.prewrite_message, message, binary))

    # @coroutine
    # def prewrite_message(self, message, binary):
    #     cls = self.__class__
    #     # Use a try block because the log decorator doesn't cooperate with @coroutine.
    #     try:
    #         with self._write_lock:
    #             future = self.write_message(message, binary)

    #             # When closing, self.write_message() return None even if it's an undocument output.
    #             # Consider it as WebSocketClosedError
    #             # For tornado versions <4.3.0 self.write_message() does not have a return value
    #             if future is None and tornado_version_info >= (4,3,0,0):
    #                 raise WebSocketClosedError

    #             yield future
    #     except WebSocketClosedError:
    #         cls.node_handle.get_logger().warn('WebSocketClosedError: Tried to write to a closed websocket',
    #             throttle_duration_sec=1.0)
    #         raise
    #     except StreamClosedError:
    #         cls.node_handle.get_logger().warn('StreamClosedError: Tried to write to a closed stream',
    #             throttle_duration_sec=1.0)
    #         raise
    #     except BadYieldError:
    #         # Tornado <4.5.0 doesn't like its own yield and raises BadYieldError.
    #         # This does not affect functionality, so pass silently only in this case.
    #         if tornado_version_info < (4, 5, 0, 0):
    #             pass
    #         else:
    #             _log_exception()
    #             raise
    #     except:
    #         _log_exception()
    #         raise

    # @log_exceptions
    # def check_origin(self, origin):
    #     return True

    # @log_exceptions
    # def get_compression_options(self):
    #     # If this method returns None (the default), compression will be disabled.
    #     # If it returns a dict (even an empty one), it will be enabled.
    #     cls = self.__class__

    #     if not cls.use_compression:
    #         return None

    #     return {}
