#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2010 Shoichi Sakane <sakane@tanu.org>, All rights reserved.
# See the file LICENSE in the top level directory for more details.
#

from __future__ import print_function

try:
    from .tiny_http_server import TinyHTTPHandler, ThreadedHTTPServer, TinyHTTPServer, DEBUG2, DEBUG3
except:
    from tiny_http_server import TinyHTTPHandler, ThreadedHTTPServer, TinyHTTPServer, DEBUG2, DEBUG3

'''
- Chunk handling referred to "4.1.  Chunked Transfer Coding in RFC 7230".
- As for the processing of 'Connection: close' and 'Connection: Keep-Alive',
  this class doesn't support persistent connection.
  i.e. it always replies with 'connection: close'.
'''

'''
4.1 Chunked Transfer Coding

 chunked-body   = *chunk
                  last-chunk
                  trailer-part
                  CRLF

 chunk          = chunk-size [ chunk-ext ] CRLF
                  chunk-data CRLF
 chunk-size     = 1*HEXDIG
 last-chunk     = 1*("0") [ chunk-ext ] CRLF

 chunk-data     = 1*OCTET ; a sequence of chunk-size octets
'''

class ChunkableHTTPRequestHandler(TinyHTTPHandler):

    __version__ = '0.1'

    max_content_size = 512*1024  # 512KB
    force_chunked = False
    chunk_max_size = 512
    chunk_header_length = 128    # chunk header length of inline or footer
    chunk_tail_buffer = 16
    chunk_read_timeout = 5

    def __init__(self, request, client_address, server, **kwargs):
        if "force_chunked" in kwargs:
            if kwargs['force_chunked'] in [ True, False ]:
                self.force_chunked = kwargs['force_chunked']
            else:
                raise ValueError('invalid value of force_chunked')
        if "chunk_max_size" in kwargs:
            if kwargs['chunk_max_size'] > 0:
                self.chunk_max_size = kwargs['chunk_max_size']
            else:
                raise ValueError('invalid value of chunk_max_size')
        if "chunk_read_timeout" in kwargs:
            if kwargs['chunk_read_timeout'] > 0:
                self.chunk_read_timeout = kwargs['chunk_read_timeout']
            else:
                raise ValueError('invalid value of chunk_read_timeout')
        TinyHTTPHandler.__init__(self, request, client_address, server)
        self.set_server_version('ChunkableHTTPServer/' + self.__version__)

    def do_PUT(self):
        pass

    def read_content(self):
        transfer_encoding = self.headers.get('Transfer-Encoding')
        if transfer_encoding:
            if transfer_encoding == 'chunked':
                self.read_chunked()
            else:
                self.logger.error('not supported such transfer_encoding %s' %
                      transfer_encoding)
        elif "Content-Length" in self.headers:
            self.post_read(self.read_length())
        else:
            self.logger.debug('Content-Length or Transfer-Encoding are not specified.')
            self.post_read(self.read_somehow())

    def read_chunked(self):
        transfer_encoding = self.headers.get('Transfer-Encoding')
        if transfer_encoding != 'chunked':
            raise RuntimeError("ERROR: chunked doesn't specified.")
        t = threading.Thread(target=self.__read_chunked)
        t.start()
        t.join(self.chunk_read_timeout)
        if t.is_alive() == True:
            self.logger.warn('timed out of thread of reading chunks.')

    def __read_chunked(self):
        total_length = 0
        contents = []
        while True:
            try:
                #
                # read the 1st line of a chunk.
                #     i.e. chunk-size [ chunk-ext ] CRLF
                # chunk_header_length bytes is enough to read the chunk header.
                #
                chunk_header = self.rfile.readline(self.chunk_header_length)
                self.logger.log(DEBUG2, 'chunk header=%s' % chunk_header)
                if chunk_header == '\r\n':
                    self.logger.log(DEBUG3, 'last-chunk does not exist.')
                    self.logger.log(DEBUG3, 'stop reading chunks anyway.')
                    chunk_size = 0
                    break
                if not chunk_header:
                    raise RuntimeError('Connection reset by peer')
                chunk_size_string = chunk_header.split(';', 1)[0]
                chunk_size = int(chunk_size_string, 16)
            except:
                raise
            if chunk_size == 0:
                self.logger.log(DEBUG3, 'last-chunk has been found.')
                break
            #
            # read a chunk
            #   don't use readline() because CR or LF may be among the chunk.
            #
            chunk = self.rfile.read(chunk_size)
            self.logger.log(DEBUG2, 'chunked size=%d' % chunk_size)
            self.logger.log(DEBUG2, 'chunk=%s' % chunk)
            self.logger.log(DEBUG3, 'chunk(hex)=%s' %
                    ' '.join([hex(x) for x in bytearray(chunk)]))
            # remove the tail.
            nl = self.rfile.read(2)
            self.logger.log(DEBUG3,
                            'tail of chunk=%s' % ' '.join([hex(x) for x in
                                                          bytearray(nl)]))
            #
            contents.append(chunk)
            total_length += chunk_size
            if total_length > self.max_content_size:
                raise ValueError('too large content > %d' %
                                 self.max_content_size)
        # cool down
        # XXX just skip the footer and CR+LF in the end.
        while True:
            try:
                footer = self.rfile.readline(self.chunk_header_length)
                self.logger.log(DEBUG2, 'footer=%s' % footer)
                if footer == '\r\n':
                    self.logger.log(DEBUG3, 'end of chunk has been found.')
                    break
                elif not footer:
                    raise RuntimeError('Connection reset by peer')
            except:
                raise
        self.post_read(contents)

    def read_somehow(self):
        '''
        may be overriddedn.
        '''
        self.post_read([])

    def send_chunked(self, code, msg_list, content_type):
        self.send_response(code)
        #self.send_header('Content-Type', content_type)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Connection', 'close')
        self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()
        self.logger.log(DEBUG2, '---BEGIN OF RESPONSE---')
        for c in msg_list:
            s = self.chunk_max_size
            bl = len(c) / s + (1 if len(c) % s else 0)
            c_frag = [ c[x * s : x * s + s] for x in range(bl) ]
            for i in c_frag:
                chunk_size = hex(len(i))[2:]
                self.wfile.write(''.join([ chunk_size, '\r\n', i, '\r\n' ]))
                self.logger.log(DEBUG2, chunk_size)
                self.logger.log(DEBUG2, "%s" % i.strip())
                self.logger.log(DEBUG3, 'hex=%s' % " ".join([ hex(x)[2:] for x
                                                             in bytearray(i) ],
                                                            '\n'))
        self.logger.log(DEBUG2, '---END OF RESPONSE---')
        self.wfile.write('0\r\n')
        self.wfile.write('\r\n')
        # 
        self.send_header('Connection', 'close')

'''
test
'''
if __name__ == '__main__':
    httpd = TinyHTTPServer(ChunkableHTTPRequestHandler)
    httpd.run()
