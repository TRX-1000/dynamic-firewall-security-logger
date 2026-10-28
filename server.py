"""Concurrent newline-framed TCP echo service. Threads handle separate clients."""
import argparse
import socketserver
from events import MAX_LINE, event, send_event

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10)
        peer = f'{self.client_address[0]}:{self.client_address[1]}'
        send_event(event('server', 'CONNECT', peer=peer), self.server.logger_host, self.server.logger_port)
        count = 0
        try:
            while True:
                line = self.rfile.readline(MAX_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_LINE or not line.endswith(b'\n'):
                    break
                self.wfile.write(line)
                self.wfile.flush()
                count += 1
        except OSError:
            pass
        finally:
            send_event(event('server', 'DISCONNECT', peer=peer, messages=count),
                       self.server.logger_host, self.server.logger_port)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--logger-host', default='10.0.0.4')
    parser.add_argument('--logger-port', type=int, default=7000)
    args = parser.parse_args()
    with Server((args.host, args.port), Handler) as server:
        server.logger_host, server.logger_port = args.logger_host, args.logger_port
        print(f'TCP echo server listening on {server.server_address}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
