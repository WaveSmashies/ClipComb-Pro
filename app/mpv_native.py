# SPDX-License-Identifier: GPL-3.0-or-later
"""Small ctypes binding to libmpv's stable C client API (no player subprocesses)."""
import ctypes as c
import os
import threading
import time
from pathlib import Path


class Node(c.Structure):
    pass


class NodeList(c.Structure):
    _fields_ = [('num', c.c_int), ('values', c.POINTER(Node)), ('keys', c.POINTER(c.c_char_p))]


class ByteArray(c.Structure):
    _fields_ = [('data', c.c_void_p), ('size', c.c_size_t)]


class NodeValue(c.Union):
    _fields_ = [('string', c.c_char_p), ('flag', c.c_int), ('int64', c.c_int64),
                ('double', c.c_double), ('list', c.POINTER(NodeList)), ('ba', c.POINTER(ByteArray))]


Node._fields_ = [('u', NodeValue), ('format', c.c_int)]


class Event(c.Structure):
    _fields_ = [('id', c.c_int), ('error', c.c_int), ('userdata', c.c_uint64), ('data', c.c_void_p)]

class EventProperty(c.Structure):
    _fields_=[('name',c.c_char_p),('format',c.c_int),('data',c.c_void_p)]


class ClientMessage(c.Structure):
    _fields_ = [('count', c.c_int), ('args', c.POINTER(c.c_char_p))]


class LogMessage(c.Structure):
    _fields_ = [('prefix', c.c_char_p), ('level', c.c_char_p), ('text', c.c_char_p), ('log_level', c.c_int)]


def decode(node):
    fmt, value = node.format, node.u
    if fmt == 1:
        return value.string.decode('utf-8', 'replace') if value.string else ''
    if fmt == 3:
        return bool(value.flag)
    if fmt == 4:
        return value.int64
    if fmt == 5:
        return value.double
    if fmt in (7, 8):
        items = value.list.contents
        values = [decode(items.values[i]) for i in range(items.num)]
        return dict(zip((items.keys[i].decode() for i in range(items.num)), values)) if fmt == 8 else values
    if fmt == 9:
        data = value.ba.contents
        return c.string_at(data.data, data.size)
    return None


class Mpv:
    def __init__(self, path, options=None):
        path = Path(path).resolve()
        self.search_path = os.add_dll_directory(str(path.parent))
        self.dll = c.CDLL(str(path))
        self.handle = None
        self.lock = threading.RLock()
        self.read_values={};self.async_values={};self.async_pending={};self.af_revision=0
        ptr = c.c_void_p
        self.bind('create', ptr)
        self.bind('initialize', c.c_int, ptr)
        self.bind('terminate_destroy', None, ptr)
        self.bind('set_option_string', c.c_int, ptr, c.c_char_p, c.c_char_p)
        self.bind('set_property_string', c.c_int, ptr, c.c_char_p, c.c_char_p)
        self.bind('get_property', c.c_int, ptr, c.c_char_p, c.c_int, ptr)
        self.bind('get_property_async',c.c_int,ptr,c.c_uint64,c.c_char_p,c.c_int)
        self.bind('command_ret', c.c_int, ptr, c.POINTER(c.c_char_p), c.POINTER(Node))
        self.bind('command_async', c.c_int, ptr, c.c_uint64, c.POINTER(c.c_char_p))
        self.bind('free_node_contents', None, c.POINTER(Node))
        self.bind('wait_event', c.POINTER(Event), ptr, c.c_double)
        self.bind('request_log_messages', c.c_int, ptr, c.c_char_p)
        self.bind('client_name', c.c_char_p, ptr)
        self.bind('error_string', c.c_char_p, c.c_int)
        self.handle = self.create()
        if not self.handle:
            raise RuntimeError('Could not create the mpv player.')
        try:
            for name, value in (options or {}).items():
                self.check(self.set_option_string(self.handle, name.encode(), str(value).encode()))
            self.check(self.initialize(self.handle))
            self.request_log_messages(self.handle, b'warn')
            self.name = self.client_name(self.handle).decode()
        except Exception:
            self.close()
            raise

    def bind(self, name, result, *arguments):
        method = getattr(self.dll, 'mpv_' + name)
        method.restype, method.argtypes = result, arguments
        setattr(self, name, method)

    def check(self, result):
        if result < 0:
            raise RuntimeError(self.error_string(result).decode('utf-8', 'replace'))

    def set(self, name, value):
        original=value
        if isinstance(value, bool):
            value = 'yes' if value else 'no'
        self.check(self.set_property_string(self.handle, name.encode(), str(value).encode('utf-8')))
        self.read_values[name]=original
        if name=='af':self.af_revision+=1

    def get(self, name, default=None):
        with self.lock:
            if not self.handle:return default
            value=self._get(name,default);self.read_values[name]=value;return value

    def request_property(self,name):
        """One outstanding asynchronous read per name; never wait for decoding."""
        if not self.handle:return None
        if name not in self.async_pending:
            token=(1<<62)+len(self.async_values)+1
            while token in self.async_pending.values():token+=1
            self.check(self.get_property_async(self.handle,token,name.encode(),6));self.async_pending[name]=token
        value,stamp=self.async_values.get(name,(None,0))
        return value if time.monotonic()-stamp<.3 else None

    def _get(self,name,default=None):
        node = Node()
        status = self.get_property(self.handle, name.encode(), 6, c.byref(node))
        if status < 0:
            return default
        try:
            return decode(node)
        finally:
            self.free_node_contents(c.byref(node))

    def command(self, *args, asynchronous=False, request=0):
        with self.lock:
            if not self.handle:
                raise RuntimeError('The player has closed.')
            return self._command(*args, asynchronous=asynchronous, request=request)

    def _command(self, *args, asynchronous=False, request=0):
        encoded = [str(arg).encode('utf-8') for arg in args]
        array = (c.c_char_p * (len(encoded) + 1))(*encoded, None)
        if asynchronous:
            self.check(self.command_async(self.handle, request, array))
            return None
        result = Node()
        self.check(self.command_ret(self.handle, array, c.byref(result)))
        try:
            return decode(result)
        finally:
            self.free_node_contents(c.byref(result))

    def events(self):
        while self.handle:
            event = self.wait_event(self.handle, 0).contents
            if not event.id:
                break
            if event.id==5 and event.userdata==(1<<61):
                # Optional meter filter commands must never become playback errors.
                continue
            data = None
            if event.id==3:
                name=next((name for name,token in self.async_pending.items() if token==event.userdata),None)
                if name:
                    prop=c.cast(event.data,c.POINTER(EventProperty)).contents
                    value=decode(c.cast(prop.data,c.POINTER(Node)).contents) if prop.format==6 and prop.data and event.error>=0 else None
                    self.async_values[name]=(value,time.monotonic());self.async_pending.pop(name,None)
            if event.id == 16:
                message = c.cast(event.data, c.POINTER(ClientMessage)).contents
                data = [message.args[i].decode('utf-8', 'replace') for i in range(message.count)]
            elif event.id == 2:
                log = c.cast(event.data, c.POINTER(LogMessage)).contents
                data = (log.prefix.decode(), log.level.decode(), log.text.decode('utf-8', 'replace').strip())
            yield event.id, event.error, event.userdata, data

    def close(self):
        with self.lock:
            if self.handle:
                self.terminate_destroy(self.handle)
                self.handle = None
            self.search_path.close()
