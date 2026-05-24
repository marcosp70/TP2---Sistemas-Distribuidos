import os
import time
import json
import shutil
import threading
from src.utils import generate_random_file, create_metadata, calculate_sha256
from src.peer import PeerNode

def clean_temp_directory():
    """
    Limpa o diretorio temporario de testes.
    """
    temp_dir = os.path.abspath("./temp")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def run_scenario(scenario, temp_base_dir):
    """
    Executa um unico cenario de teste.
    """
    scenario_id = scenario["id"]
    name = scenario["name"]
    num_peers = scenario["peers"]
    block_size = scenario["block_size"]
    file_size = scenario["file_size"]
    
    print("=" * 80)
    print(f"INICIANDO: {name}")
    print(f"  Peers: {num_peers} | Bloco: {block_size} Bytes | Arquivo: {file_size / 1024:.1f} KB")
    print("=" * 80)
    
    # Pasta especifica do cenario
    scen_dir = os.path.join(temp_base_dir, f"scenario_{scenario_id}")
    os.makedirs(scen_dir, exist_ok=True)
    
    # 1. Geração do arquivo de origem no Seeder inicial (Peer A)
    seeder_dir = os.path.join(scen_dir, "peer_A")
    os.makedirs(seeder_dir, exist_ok=True)
    source_file_path = os.path.join(seeder_dir, "origem.bin")
    
    print(f"[*] Gerando arquivo de teste aleatorio em {source_file_path}...")
    generate_random_file(source_file_path, file_size)
    original_hash = calculate_sha256(source_file_path)
    
    # 2. Criação do arquivo de metadados
    meta_path = os.path.join(scen_dir, "arquivo.meta")
    print(f"[*] Gerando metadados do arquivo em {meta_path}...")
    create_metadata(source_file_path, block_size, meta_path)
    
    # 3. Definição de topologia de rede estática
    # Portas base: 8000 para A, 8001 para B, 8002 para C, 8003 para D
    ports = {
        "A": 8000 + scenario_id * 10,
        "B": 8001 + scenario_id * 10,
        "C": 8002 + scenario_id * 10,
        "D": 8003 + scenario_id * 10
    }
    
    # Configura vizinhos conforme a topologia
    # A (Seeder): nao conecta ativamente a ninguem
    # B (Leecher): se conecta a A
    # C (Leecher): se conecta a A e B
    # D (Leecher): se conecta a B e C
    neighbors = {
        "A": [],
        "B": [("127.0.0.1", ports["A"])],
        "C": [("127.0.0.1", ports["A"]), ("127.0.0.1", ports["B"])],
        "D": [("127.0.0.1", ports["B"]), ("127.0.0.1", ports["C"])]
    }
    
    # Instancia os Peers
    peer_instances = {}
    peer_names = ["A", "B", "C", "D"][:num_peers]
    
    for name_char in peer_names:
        p_dir = os.path.join(scen_dir, f"peer_{name_char}")
        os.makedirs(p_dir, exist_ok=True)
        
        # O arquivo de destino de cada peer
        p_file = os.path.join(p_dir, "origem.bin" if name_char == "A" else "download.bin")
        
        node = PeerNode(
            peer_id=name_char,
            ip="127.0.0.1",
            port=ports[name_char],
            neighbor_addresses=neighbors[name_char],
            file_path=p_file,
            meta_path=meta_path
        )
        peer_instances[name_char] = node
        
    # 4. Inicializa os nós Peers (em threads dedicadas para o teste em lote)
    print("[*] Iniciando todos os nos Peers...")
    for node in peer_instances.values():
        node.start()
        
    # 5. Monitoramento do download dos Leechers
    leechers = [peer_instances[k] for k in peer_names if k != "A"]
    timeout = max(60.0, file_size / (50 * 1024))  # tempo limite dinâmico de timeout
    start_time = time.time()
    
    print(f"[*] Monitorando downloads (Timeout limite: {timeout:.1f}s)...")
    
    all_done = False
    while time.time() - start_time < timeout:
        # Verifica se todos os Leechers finalizaram
        statuses = [p.download_complete for p in leechers]
        if all(statuses):
            all_done = True
            break
        time.sleep(0.5)
        
    duration = time.time() - start_time
    
    # 6. Avaliação e Verificação
    results = {}
    print("\n" + "-" * 50)
    print(f"RESULTADOS DA AVALIACAO - {name.upper()}")
    print("-" * 50)
    
    if all_done:
        print(f"STATUS: SUCESSO! Todos os peers completaram a transferência em {duration:.2f}s.")
    else:
        print("STATUS: TIMEOUT ou FALHA na transferência!")
        
    for name_char in peer_names:
        p_node = peer_instances[name_char]
        p_results = {
            "peer_id": name_char,
            "completed": p_node.download_complete,
            "duration": None,
            "throughput_kb_s": None,
            "hash_matches": False,
            "block_sources": p_node.block_sources
        }
        
        if name_char == "A":
            p_results["completed"] = True
            p_results["duration"] = 0.0
            p_results["hash_matches"] = True
            print(f" Peer A (Seeder): Atuando na rede.")
        else:
            if p_node.download_complete:
                p_results["duration"] = p_node.end_time - p_node.start_time
                p_results["throughput_kb_s"] = (file_size / 1024) / p_results["duration"]
                
                # Valida arquivo final e hash
                downloaded_hash = calculate_sha256(p_node.file_path)
                p_results["hash_matches"] = downloaded_hash == original_hash
                
                print(f" Peer {name_char} (Leecher): COMPLETADO em {p_results['duration']:.2f}s | "
                      f"Velocidade: {p_results['throughput_kb_s']:.2f} KB/s | Integrity SHA-256: {'OK' if p_results['hash_matches'] else 'FALHA'}")
            else:
                print(f" Peer {name_char} (Leecher): NAO CONCLUIDO!")
                
        results[name_char] = p_results
        
    # 7. Finalização e Parada dos Sockets dos Peers
    print("[*] Encerrando sockets de todos os nos...")
    for node in peer_instances.values():
        node.stop()
        
    # Limpa threads ativas
    time.sleep(1.0)
    
    return {
        "scenario_id": scenario_id,
        "name": name,
        "success": all_done,
        "total_duration": duration,
        "peers_data": results
    }

def main():
    print("=" * 80)
    print("     INICIANDO SUITE DE TESTES P2P - TABELA 1 ESPECIFICADA")
    print("=" * 80)
    
    temp_base_dir = clean_temp_directory()
    
    # Tabela 1: Parâmetros de Configuração
    scenarios = [
        {"id": 1, "name": "Cenario 1: 2 Peers, Bloco 1KB, File 10KB", "peers": 2, "block_size": 1024, "file_size": 10 * 1024},
        {"id": 2, "name": "Cenario 2: 4 Peers, Bloco 4KB, File 20KB", "peers": 4, "block_size": 4096, "file_size": 20 * 1024},
        {"id": 3, "name": "Cenario 3: 4 Peers, Bloco 1KB, File 1MB", "peers": 4, "block_size": 1024, "file_size": 1 * 1024 * 1024},
        {"id": 4, "name": "Cenario 4: 4 Peers, Bloco 4KB, File 5MB", "peers": 4, "block_size": 4096, "file_size": 5 * 1024 * 1024},
        {"id": 5, "name": "Cenario 5: 4 Peers, Bloco 4KB, File 10MB", "peers": 4, "block_size": 4096, "file_size": 10 * 1024 * 1024},
        {"id": 6, "name": "Cenario 6: 4 Peers, Bloco 4KB, File 20MB", "peers": 4, "block_size": 4096, "file_size": 20 * 1024 * 1024},
    ]
    
    all_results = []
    
    for sc in scenarios:
        res = run_scenario(sc, temp_base_dir)
        all_results.append(res)
        print("\n[*] Aguardando 2s para liberacao de portas TCP antes do proximo teste...")
        time.sleep(2.0)
        
    # Escreve o arquivo JSON com os resultados dos testes para uso do gerador de PDF
    results_json_path = os.path.abspath("./test_results.json")
    with open(results_json_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=4, ensure_ascii=False)
        
    print("=" * 80)
    print("     TESTES COMPLETADOS COM SUCESSO!")
    print(f"Resultados detalhados salvos em: {results_json_path}")
    print("=" * 80)

if __name__ == "__main__":
    main()
