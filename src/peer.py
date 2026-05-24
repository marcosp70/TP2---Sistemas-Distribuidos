import os
import sys
import socket
import threading
import time
import argparse
try:
    from src.utils import calculate_sha256, load_metadata
except ModuleNotFoundError:
    from utils import calculate_sha256, load_metadata

# Protocol Message Types
MSG_HANDSHAKE = 0x01
MSG_BITFIELD = 0x02
MSG_HAVE = 0x03
MSG_REQUEST = 0x04
MSG_PIECE = 0x05

class PeerConnection:
    """
    Representa uma conexao ativa com outro Peer, contendo o socket e um lock para escrita.
    """
    def __init__(self, sock, peer_id=None):
        self.sock = sock
        self.peer_id = peer_id
        self.lock = threading.Lock()

    def send(self, type_id, payload=b""):
        with self.lock:
            try:
                msg = bytes([type_id]) + payload
                header = len(msg).to_bytes(4, byteorder='big')
                self.sock.sendall(header + msg)
                return True
            except Exception:
                return False

class PeerNode:
    def __init__(self, peer_id, ip, port, neighbor_addresses, file_path, meta_path):
        self.peer_id = peer_id
        self.ip = ip
        self.port = port
        self.neighbor_addresses = neighbor_addresses  # lista de (ip, port)
        self.file_path = file_path
        self.meta_path = meta_path
        
        # Carrega metadados do arquivo
        self.metadata = load_metadata(meta_path)
        self.file_name = self.metadata["file_name"]
        self.file_size = self.metadata["file_size"]
        self.chunk_size = self.metadata["chunk_size"]
        self.num_chunks = self.metadata["num_chunks"]
        self.expected_file_hash = self.metadata["file_hash"]
        self.chunk_hashes = self.metadata["chunk_hashes"]
        
        # Estado do Peer
        self.bitfield = [False] * self.num_chunks
        self.lock = threading.Lock()
        self.active_connections = []  # lista de PeerConnection
        self.is_running = True
        self.download_complete = False
        
        # Logs de recebimento de blocos para fins de relatorio
        self.block_sources = {}  # chunk_idx -> peer_id do provedor
        self.start_time = None
        self.end_time = None

        # Configura arquivo de saida
        # Se for o Seeder inicial, o arquivo original ja deve existir e estar completo.
        # Caso contrario, criamos o arquivo vazio pre-alocado para preencher com blocos recebidos.
        self._initialize_file()

    def _initialize_file(self):
        """
        Verifica se ja possui o arquivo completo ou inicializa um arquivo vazio pre-alocado.
        """
        if os.path.exists(self.file_path) and os.path.getsize(self.file_path) == self.file_size:
            # Verifica se o hash bate
            current_hash = calculate_sha256(self.file_path)
            if current_hash == self.expected_file_hash:
                self.log("Arquivo de origem ja existe e esta integro. Iniciando como Seeder.")
                self.bitfield = [True] * self.num_chunks
                self.download_complete = True
                return
        
        # Caso contrario, cria/sobrescreve o arquivo pre-alocado com zeros
        self.log(f"Pre-alocando arquivo de destino de {self.file_size} bytes...")
        parent_dir = os.path.dirname(self.file_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
            
        with open(self.file_path, 'wb') as f:
            # Escreve um byte no final do arquivo para aloca-lo de forma eficiente
            if self.file_size > 0:
                f.seek(self.file_size - 1)
                f.write(b'\x00')
            else:
                f.write(b'')
        self.log("Arquivo de destino pre-alocado com sucesso. Iniciando como Leecher.")

    def log(self, message):
        """
        Imprime logs formatados e sincronizados de forma thread-safe.
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            print(f"[{timestamp}] [Peer {self.peer_id}] {message}", flush=True)

    def start(self):
        """
        Inicia o servidor e os clientes do Peer.
        """
        self.start_time = time.time()
        
        # Inicia a thread do Servidor (escuta conexoes de entrada)
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()
        
        # Inicia conexoes de Cliente com todos os vizinhos configurados
        self.client_threads = []
        for neighbor_ip, neighbor_port in self.neighbor_addresses:
            t = threading.Thread(
                target=self._connect_to_neighbor, 
                args=(neighbor_ip, neighbor_port), 
                daemon=True
            )
            t.start()
            self.client_threads.append(t)

    def stop(self):
        """
        Para o nó e fecha todas as conexoes.
        """
        self.is_running = False
        with self.lock:
            for conn in self.active_connections:
                try:
                    conn.sock.close()
                except Exception:
                    pass
            self.active_connections.clear()

    def _recv_all(self, sock, size):
        data = bytearray()
        while len(data) < size:
            try:
                packet = sock.recv(size - len(data))
                if not packet:
                    return None
                data.extend(packet)
            except socket.timeout:
                continue
            except Exception:
                return None
        return bytes(data)

    def _recv_msg(self, sock):
        header = self._recv_all(sock, 4)
        if not header:
            return None, None
        msg_len = int.from_bytes(header, byteorder='big')
        msg = self._recv_all(sock, msg_len)
        if not msg or len(msg) < 1:
            return None, None
        type_id = msg[0]
        payload = msg[1:]
        return type_id, payload

    def _broadcast_have(self, chunk_idx):
        """
        Envia mensagem HAVE para todos os vizinhos conectados.
        """
        payload = chunk_idx.to_bytes(4, byteorder='big')
        # Faz copia da lista para evitar race conditions
        with self.lock:
            connections = list(self.active_connections)
        
        for conn in connections:
            conn.send(MSG_HAVE, payload)

    # ==================== MODULO SERVIDOR (Incoming Connections) ====================

    def _run_server(self):
        self.log(f"Servidor iniciado na porta {self.port}...")
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server_sock.bind((self.ip, self.port))
            server_sock.listen(10)
        except Exception as e:
            self.log(f"Erro ao bindar servidor na porta {self.port}: {e}")
            return

        while self.is_running:
            try:
                server_sock.settimeout(1.0)
                sock, addr = server_sock.accept()
                sock.settimeout(5.0)
                t = threading.Thread(target=self._handle_incoming_connection, args=(sock,), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.is_running:
                    self.log(f"Erro ao aceitar conexao de entrada: {e}")
                break
        
        try:
            server_sock.close()
        except Exception:
            pass

    def _handle_incoming_connection(self, sock):
        """
        Trata a conexao de um vizinho que se conectou a nossa porta de servidor.
        """
        conn = PeerConnection(sock)
        try:
            # 1. Espera Handshake do cliente
            type_id, payload = self._recv_msg(sock)
            if type_id != MSG_HANDSHAKE or not payload:
                sock.close()
                return
            
            client_id_len = payload[0]
            client_peer_id = payload[1:1+client_id_len].decode('utf-8')
            conn.peer_id = client_peer_id
            
            # 2. Responde Handshake
            my_id_bytes = self.peer_id.encode('utf-8')
            handshake_payload = bytes([len(my_id_bytes)]) + my_id_bytes
            if not conn.send(MSG_HANDSHAKE, handshake_payload):
                sock.close()
                return
            
            # 3. Envia nosso bitfield
            with self.lock:
                bitfield_str = "".join(["1" if b else "0" for b in self.bitfield])
            if not conn.send(MSG_BITFIELD, bitfield_str.encode('utf-8')):
                sock.close()
                return
            
            # 4. Espera o bitfield do cliente
            type_id, payload = self._recv_msg(sock)
            if type_id != MSG_BITFIELD or not payload:
                sock.close()
                return
            
            client_bitfield = [char == '1' for char in payload.decode('utf-8')]
            self.log(f"Conexao de entrada estabelecida com Vizinho {client_peer_id}.")
            
            with self.lock:
                self.active_connections.append(conn)
            
            # 5. Loop de tratamento de mensagens do cliente (Servindo blocos)
            while self.is_running:
                type_id, payload = self._recv_msg(sock)
                if type_id is None:
                    break
                
                if type_id == MSG_REQUEST:
                    if len(payload) < 4:
                        continue
                    chunk_idx = int.from_bytes(payload[:4], byteorder='big')
                    
                    # Le e envia o bloco solicitado se tivermos ele
                    has_chunk = False
                    with self.lock:
                        if chunk_idx < self.num_chunks:
                            has_chunk = self.bitfield[chunk_idx]
                    
                    if has_chunk:
                        # Le do arquivo
                        try:
                            with open(self.file_path, 'rb') as f:
                                f.seek(chunk_idx * self.chunk_size)
                                chunk_data = f.read(self.chunk_size)
                            
                            # Envia bloco (PIECE: 4 bytes index + dados)
                            piece_payload = chunk_idx.to_bytes(4, byteorder='big') + chunk_data
                            conn.send(MSG_PIECE, piece_payload)
                        except Exception as e:
                            self.log(f"Erro ao ler bloco {chunk_idx} do arquivo para enviar: {e}")
                    else:
                        self.log(f"Vizinho {client_peer_id} solicitou bloco {chunk_idx} que nao possuimos!")
                
                elif type_id == MSG_HAVE:
                    if len(payload) < 4:
                        continue
                    have_idx = int.from_bytes(payload[:4], byteorder='big')
                    # Apenas registra que o vizinho agora possui este bloco
                    pass
                    
        except Exception as e:
            pass
        finally:
            with self.lock:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)
            try:
                sock.close()
            except Exception:
                pass
            if conn.peer_id:
                self.log(f"Conexao de entrada com Vizinho {conn.peer_id} encerrada.")

    # ==================== MODULO CLIENTE (Outgoing Connections) ====================

    def _connect_to_neighbor(self, neighbor_ip, neighbor_port):
        """
        Tenta se conectar e gerencia a conexao ativa com um Peer vizinho.
        """
        retry_interval = 2.0
        sock = None
        
        while self.is_running and not self.download_complete:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((neighbor_ip, neighbor_port))
                break
            except Exception:
                try:
                    sock.close()
                except Exception:
                    pass
                time.sleep(retry_interval)
                continue
        
        if not self.is_running or not sock:
            return

        conn = PeerConnection(sock)
        try:
            # 1. Envia Handshake
            my_id_bytes = self.peer_id.encode('utf-8')
            handshake_payload = bytes([len(my_id_bytes)]) + my_id_bytes
            if not conn.send(MSG_HANDSHAKE, handshake_payload):
                sock.close()
                return
            
            # 2. Espera Handshake de volta
            type_id, payload = self._recv_msg(sock)
            if type_id != MSG_HANDSHAKE or not payload:
                sock.close()
                return
            
            neighbor_id_len = payload[0]
            neighbor_peer_id = payload[1:1+neighbor_id_len].decode('utf-8')
            conn.peer_id = neighbor_peer_id
            
            # 3. Espera o bitfield do vizinho
            type_id, payload = self._recv_msg(sock)
            if type_id != MSG_BITFIELD or not payload:
                sock.close()
                return
            
            neighbor_bitfield = [char == '1' for char in payload.decode('utf-8')]
            
            # 4. Envia nosso bitfield
            with self.lock:
                bitfield_str = "".join(["1" if b else "0" for b in self.bitfield])
            if not conn.send(MSG_BITFIELD, bitfield_str.encode('utf-8')):
                sock.close()
                return
            
            self.log(f"Conexao de saida estabelecida com Vizinho {neighbor_peer_id}.")
            
            with self.lock:
                self.active_connections.append(conn)

            # 5. Loop do Cliente (Requisitando blocos que faltam)
            while self.is_running:
                # Se completou o download de todos os blocos, nao precisamos pedir mais nada.
                # Apenas mantemos a conexao aberta para receber eventuais notificacoes ou mensagens.
                if self.download_complete:
                    # Roda em modo passivo apenas ouvindo atualizacoes de HAVE
                    sock.settimeout(1.0)
                    try:
                        type_id, payload = self._recv_msg(sock)
                        if type_id is None:
                            break
                        if type_id == MSG_HAVE:
                            have_idx = int.from_bytes(payload[:4], byteorder='big')
                            if have_idx < len(neighbor_bitfield):
                                neighbor_bitfield[have_idx] = True
                    except socket.timeout:
                        continue
                    except Exception:
                        break
                    continue
                
                # Escolhe um bloco que nos nao temos, mas o vizinho tem
                target_chunk_idx = None
                with self.lock:
                    needed_indices = []
                    for idx in range(self.num_chunks):
                        if not self.bitfield[idx] and idx < len(neighbor_bitfield) and neighbor_bitfield[idx]:
                            needed_indices.append(idx)
                    
                    if needed_indices:
                        # Selecao sequencial simples (ou random para diversificar, usaremos sequencial)
                        target_chunk_idx = needed_indices[0]
                
                if target_chunk_idx is None:
                    # Vizinho nao tem nenhum bloco util no momento. Aguarda e verifica novamente.
                    time.sleep(0.5)
                    # Verifica tambem se ha mensagens pendentes de HAVE enviadas pelo vizinho
                    sock.settimeout(0.1)
                    try:
                        type_id, payload = self._recv_msg(sock)
                        if type_id == MSG_HAVE:
                            have_idx = int.from_bytes(payload[:4], byteorder='big')
                            if have_idx < len(neighbor_bitfield):
                                neighbor_bitfield[have_idx] = True
                    except Exception:
                        pass
                    continue
                
                # Solicita o bloco
                self.log(f"Solicitando bloco {target_chunk_idx} do Vizinho {neighbor_peer_id}...")
                request_payload = target_chunk_idx.to_bytes(4, byteorder='big')
                if not conn.send(MSG_REQUEST, request_payload):
                    break
                
                # Espera a resposta da peça (tratando outras mensagens no caminho como HAVE)
                sock.settimeout(5.0)
                got_piece = False
                while self.is_running and not got_piece:
                    try:
                        type_id, payload = self._recv_msg(sock)
                        if type_id is None:
                            break
                        
                        if type_id == MSG_HAVE:
                            # Registra atualizacao de posse do vizinho
                            have_idx = int.from_bytes(payload[:4], byteorder='big')
                            if have_idx < len(neighbor_bitfield):
                                neighbor_bitfield[have_idx] = True
                        
                        elif type_id == MSG_PIECE:
                            if len(payload) < 4:
                                continue
                            piece_idx = int.from_bytes(payload[:4], byteorder='big')
                            piece_data = payload[4:]
                            
                            if piece_idx != target_chunk_idx:
                                # Recebeu bloco diferente do solicitado (ignora ou trata)
                                continue
                            
                            # Valida integridade do bloco recebido usando o hash dos metadados
                            expected_chunk_hash = self.chunk_hashes[piece_idx]
                            import hashlib
                            received_chunk_hash = hashlib.sha256(piece_data).hexdigest()
                            
                            if received_chunk_hash == expected_chunk_hash:
                                # Grava bloco no arquivo pre-alocado
                                with self.lock:
                                    with open(self.file_path, 'r+b') as f:
                                        f.seek(piece_idx * self.chunk_size)
                                        f.write(piece_data)
                                    self.bitfield[piece_idx] = True
                                    self.block_sources[piece_idx] = neighbor_peer_id
                                
                                num_downloaded = sum(self.bitfield)
                                self.log(f"Bloco {piece_idx} recebido com sucesso de {neighbor_peer_id} e validado! Progresso: {num_downloaded}/{self.num_chunks}")
                                
                                # Notifica os demais vizinhos que agora temos esse bloco
                                self._broadcast_have(piece_idx)
                                
                                # Verifica se concluiu o download de tudo
                                if num_downloaded == self.num_chunks:
                                    self._verify_and_finalize()
                                
                                got_piece = True
                            else:
                                self.log(f"AVISO: Bloco {piece_idx} recebido de {neighbor_peer_id} falhou na checagem hash SHA-256! Descartando e requisitando novamente.")
                                # Da um pequeno delay antes de tentar novamente
                                time.sleep(0.5)
                                got_piece = True  # Sai do loop interno para tentar escolher peça novamente
                                
                    except socket.timeout:
                        self.log(f"Timeout ao aguardar bloco {target_chunk_idx} de {neighbor_peer_id}.")
                        break
                    except Exception as e:
                        self.log(f"Erro ao processar bloco recebido de {neighbor_peer_id}: {e}")
                        break
                
        except Exception as e:
            pass
        finally:
            with self.lock:
                if conn in self.active_connections:
                    self.active_connections.remove(conn)
            try:
                sock.close()
            except Exception:
                pass
            if conn.peer_id:
                self.log(f"Conexao de saida com Vizinho {conn.peer_id} encerrada.")

    def _verify_and_finalize(self):
        """
        Realiza a checagem global do checksum do arquivo remontado e finaliza o download.
        """
        self.log("Todos os blocos recebidos. Calculando hash SHA-256 global...")
        final_hash = calculate_sha256(self.file_path)
        
        if final_hash == self.expected_file_hash:
            self.end_time = time.time()
            duration = self.end_time - self.start_time
            self.download_complete = True
            self.log(f"ARQUIVO REMONTADO COM SUCESSO! Hash bateu com o esperado: {final_hash[:16]}...")
            self.log(f"Tempo de download: {duration:.2f} segundos. Velocidade media: {(self.file_size / (1024 * duration)):.2f} KB/s")
        else:
            self.log(f"ERRO CRITICO: Arquivo remontado esta corrompido! Hash obtido: {final_hash}, Hash esperado: {self.expected_file_hash}")
            # Reseta bitfield dos blocos que nao batem (nossa estrategia descarta tudo neste caso simples para re-download)
            # Para fins do TP simples, apenas avisamos e encerramos.

# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="No Peer-to-Peer Simetrico (Cliente/Servidor)")
    parser.add_argument("--id", required=True, help="Identificador unico do Peer (ex: A, B, C, D)")
    parser.add_argument("--ip", default="127.0.0.1", help="Endereco IP para bind do servidor")
    parser.add_argument("--port", type=int, required=True, help="Porta de escuta do servidor")
    parser.add_argument("--neighbors", default="", help="Lista de vizinhos IP:Porta separados por virgula (ex: 127.0.0.1:8001,127.0.0.1:8002)")
    parser.add_argument("--file", required=True, help="Caminho do arquivo correspondente")
    parser.add_argument("--meta", required=True, help="Caminho do arquivo de metadados (.meta)")
    
    args = parser.parse_args()
    
    # Processa endereços dos vizinhos
    neighbor_list = []
    if args.neighbors:
        for addr_str in args.neighbors.split(","):
            if ":" in addr_str:
                nip, nport = addr_str.strip().split(":")
                neighbor_list.append((nip, int(nport)))
                
    peer = PeerNode(
        peer_id=args.id,
        ip=args.ip,
        port=args.port,
        neighbor_addresses=neighbor_list,
        file_path=args.file,
        meta_path=args.meta
    )
    
    peer.start()
    
    try:
        # Mantem o script rodando
        while peer.is_running:
            time.sleep(0.5)
            if peer.download_complete:
                # Opcional: Se quiser encerrar após completar o download e servir um pouco
                # No P2P costuma-se manter aberto para continuar servindo (Seeder).
                # Para fins de teste, mantemos rodando ate o runner finalizar o processo.
                pass
    except KeyboardInterrupt:
        peer.log("Encerrando no Peer sob solicitacao do usuario...")
        peer.stop()
        sys.exit(0)
