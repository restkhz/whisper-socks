import logging
import select
import socket
import struct
import _compress
import ipaddress
import sys, getopt
from socketserver import ThreadingMixIn, TCPServer, StreamRequestHandler

DEBUG=0

logging.basicConfig(level= logging.DEBUG if DEBUG else logging.INFO)
SOCKS_VERSION = 5

total_send = total_c_send = total_recv = total_c_recv = 0


class ThreadingTCPServer(ThreadingMixIn, TCPServer):
    pass


class SocksProxy(StreamRequestHandler):
    username = 'username'
    password = 'password'
    #server_ip = '3.64.11.52'
    server_ip = '127.0.0.1'
    server_port = 9010
    token = 'meow'



    def handle(self):
        global total_send, total_c_send, total_recv, total_c_recv

        logging.info('Accepting connection from %s:%s' % self.client_address)

        # greeting header
        # read and unpack 2 bytes from a client
        header = self.connection.recv(2)
        version, nmethods = struct.unpack("!BB", header)

        # socks 5
        assert version == SOCKS_VERSION
        assert nmethods > 0

        # get available methods
        methods = self.get_available_methods(nmethods)

        # accept only USERNAME/PASSWORD auth
        if 2 not in set(methods):
            # close connection
            self.server.close_request(self.request)
            return

        # send welcome message
        self.connection.sendall(struct.pack("!BB", SOCKS_VERSION, 2))

        if not self.verify_credentials():
            return
        logging.debug('Handshake ended with %s:%s' % self.client_address)

        # request
        connection_info = self.connection.recv(4)
        logging.debug('Received: %s', connection_info)
        version, cmd, _, address_type = struct.unpack("!BBBB", connection_info)
        assert version == SOCKS_VERSION

        if address_type == 1:  # IPv4
            address = socket.inet_ntoa(self.connection.recv(4))
        elif address_type == 3:  # Domain name
            domain_length = self.connection.recv(1)[0]
            address = self.connection.recv(domain_length)
            address = socket.gethostbyname(address)
        port = struct.unpack('!H', self.connection.recv(2))[0]

        # reply
        try:
            if cmd == 1:  # CONNECT
                #remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                #remote.connect((address, port))

                remote_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

                remote_server.connect((self.server_ip, self.server_port))
                logging.info('Connected to %s %s' % (self.server_ip, self.server_port))

                #bind_address = remote.getsockname()
                logging.info('Request: %s %s' % (address, port))
            else:
                self.server.close_request(self.request)

            #addr = struct.unpack("!I", socket.inet_aton(bind_address[0]))[0]
            #port = bind_address[1]
            #reply = struct.pack("!BBBBIH", SOCKS_VERSION, 0, 0, 1,addr, port)
            reply = struct.pack("!BBBBIH", SOCKS_VERSION, 0, 0, 1, int(ipaddress.IPv4Address(address)), port)

        except Exception as err:
            logging.error(err)
            # return connection refused error
            reply = self.generate_failed_reply(address_type, 5)
            raise err if DEBUG else None

        self.connection.sendall(reply)

        # establish data exchange
        if reply[1] == 0 and cmd == 1:
            remote_server.send(socket.inet_aton(address) + struct.pack('!H', port))
            recv, c_recv, send, c_send = self.exchange_loop(self.connection, remote_server) # goto loop
            send_cmp_rate = recv_cmp_rate = session_ratio = 0
            if send != 0:
                send_cmp_rate = c_send/send
            if recv != 0:
                recv_cmp_rate = c_recv/recv
                session_ratio = (c_send+c_recv)/(send+recv)

            total_send += send
            total_c_send += c_send
            total_recv += recv
            total_c_recv += c_recv

            logging.info("Total send/compressed: %s/%s Rate: %s" % (send, c_send, send_cmp_rate))
            logging.info("Total recv/compressed: %s/%s Rate: %s" % (recv, c_recv, recv_cmp_rate))
            logging.info("Session compression ratio: %s" % (session_ratio))
            logging.info("[Total compression ratio: %s]" % ((total_c_recv + total_c_send)/(total_recv + total_send)))

        self.server.close_request(self.request)
        logging.info('Session closed %s:%s' % (address, port))


    def get_available_methods(self, n):
        methods = []
        for i in range(n):
            methods.append(ord(self.connection.recv(1)))
        return methods

    def verify_credentials(self):
        version = ord(self.connection.recv(1))
        assert version == 1

        username_len = ord(self.connection.recv(1))
        username = self.connection.recv(username_len).decode('utf-8')

        password_len = ord(self.connection.recv(1))
        password = self.connection.recv(password_len).decode('utf-8')

        if username == self.username and password == self.password:
            # success, status = 0
            response = struct.pack("!BB", version, 0)
            self.connection.sendall(response)
            return True

        # failure, status != 0
        response = struct.pack("!BB", version, 0xFF)
        self.connection.sendall(response)
        self.server.close_request(self.request)
        return False

    def generate_failed_reply(self, address_type, error_number):
        return struct.pack("!BBBBIH", SOCKS_VERSION, error_number, 0, address_type, 0, 0)

    def exchange_loop(self, client, remote):
        global cmp_dict, cmp_level, collect_data
        recv = c_recv = send = c_send = 0

        while True:
            # wait until client or remote is available for read
            r, w, e = select.select([client, remote], [], [])

            if client in r:
                data_raw = client.recv(8192)

                if data_raw == b'':
                    break

                logging.debug('SEND Raw length {}'.format(len(data_raw)))
                data = _compress.compress(data_raw, cmp_level, cmp_dict, collect_data) #compress
                length = len(data)
                data = struct.pack('!H',length) + data
                logging.debug('SEND Compressed length {}'.format(len(data)))

                send += len(data_raw)
                c_send += len(data)

                if remote.send(data) <= 0:
                    break

            if remote in r:
                length = remote.recv(2)

                length = struct.unpack("!H", length)[0]
                data_raw = remote.recv(length)

                len_trans = len(data_raw)
                while len_trans < length:
                    data_raw += remote.recv(length-len_trans)
                    len_trans = len(data_raw)

                logging.debug('RECV Compressed length {}'.format(len(data_raw)))
                data = _compress.decompress(data_raw, cmp_dict, collect_data) #decompress
                logging.debug('RECV Raw length {}'.format(len(data)))

                recv += len(data)
                c_recv += len(data_raw)

                if client.send(data) <= 0:
                    break
        return recv, c_recv, send, c_send

cmp_level = 0
cmp_dict = './dict'
collect_data = False

if __name__ == '__main__':
    try:
        opts, args = getopt.getopt(sys.argv[1:],"l:d:c")
    except getopt.GetoptError:
        print('client.py -l <compression_level> -d <dict> -c\n\nUse "-c" to collect data for training.\nUse "-d" to specify a dictionary for zstd.')
        sys.exit(2)

    for opt, arg in opts:
        if opt == 'l':
            cmp_level = arg
        if opt == 'd':
            cmp_dict = arg
        if opt =='-c':
            collect_data = True

    with ThreadingTCPServer(('127.0.0.1', 9011), SocksProxy) as server:
        logging.info('Starting client-side socks5 server ..')
        server.serve_forever()
