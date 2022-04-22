import logging
import select
import socket
import struct
import sys, getopt
import _compress
import ipaddress
from socketserver import ThreadingMixIn, TCPServer, StreamRequestHandler

logging.basicConfig(level=logging.DEBUG)
SOCKS_VERSION = 5


class ThreadingTCPServer(ThreadingMixIn, TCPServer):
    pass


class SocksProxy(StreamRequestHandler):

    def handle(self):
        logging.info('Accepting connection from %s:%s' % self.client_address)

        # New request, handshaking from Client-side.

        try:
            target_addr, target_port = struct.unpack("!IH", self.connection.recv(6))
            target_addr = str(ipaddress.IPv4Address(target_addr))

            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.connect((target_addr, target_port))
            self.exchange_loop(self.connection, remote)
            logging.info('Forward to %s:%s'% (target_addr, target_port))

        except Exception as err:
            logging.error(err)
            raise err

        self.exchange_loop(self.connection, remote)

        self.server.close_request(self.request)
        logging.info('Session ended %s:%s' % self.client_address)

    def exchange_loop(self, client, remote):
        global cmp_dict, cmp_level
        while True:
            # wait until client or remote is available for read
            r, w, e = select.select([client, remote], [], [])

            if client in r:
                length = client.recv(2) #Try to get compressed data length.
                if length == b'':
                    break
                length = struct.unpack("!H", length)[0]

                data_raw = client.recv(length)

                len_trans = len(data_raw) #Sometimes we got a broken data, we need to retrieve all the data.
                while len_trans < length:
                    data_raw += client.recv(length-len_trans)
                    len_trans = len(data_raw)

                data = _compress.decompress(data_raw, cmp_dict) #decompress

                if remote.send(data) <= 0:
                    break

            if remote in r:
                data_raw = remote.recv(8192)

                data = _compress.compress(data_raw, cmp_level, cmp_dict) #compress

                length = len(data)
                data = struct.pack('!H',length) + data

                if client.send(data) <= 0:
                    break



cmp_level = 0
cmp_dict = './dict'

if __name__ == '__main__':
    try:
        opts, args = getopt.getopt(sys.argv[1:],"l:d:")
    except getopt.GetoptError:
        print('server.py -l <compression_level> -d <dict>')
        sys.exit(2)

    for opt, arg in opts:
        if opt == 'l':
            cmp_level = arg
        if opt == 'd':
            cmp_dict = arg


    with ThreadingTCPServer(('0.0.0.0', 9010), SocksProxy) as server:
        logging.info('Starting server-side proxy server ..')
        server.serve_forever()
