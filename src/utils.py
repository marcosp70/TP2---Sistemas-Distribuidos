import os
import json
import hashlib
import random

def calculate_sha256(data_or_path):
    """
    Calcula o hash SHA-256 de um arquivo (se for string de caminho) ou de bytes.
    """
    sha256 = hashlib.sha256()
    if isinstance(data_or_path, (str, bytes)) and os.path.exists(data_or_path):
        with open(data_or_path, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
    else:
        sha256.update(data_or_path if isinstance(data_or_path, bytes) else data_or_path.encode('utf-8'))
    return sha256.hexdigest()

def create_metadata(file_path, chunk_size, output_meta_path):
    """
    Divide o arquivo de origem conceitualmente em blocos de chunk_size bytes,
    calcula o hash SHA-256 global e de cada bloco individual, e salva os metadados JSON.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Arquivo de origem nao encontrado: {file_path}")
    
    file_size = os.path.getsize(file_path)
    file_hash = calculate_sha256(file_path)
    
    chunk_hashes = []
    num_chunks = 0
    
    with open(file_path, 'rb') as f:
        while True:
            chunk_data = f.read(chunk_size)
            if not chunk_data:
                break
            # Calcula SHA-256 do bloco individual
            chunk_hash = hashlib.sha256(chunk_data).hexdigest()
            chunk_hashes.append(chunk_hash)
            num_chunks += 1
            
    metadata = {
        "file_name": os.path.basename(file_path),
        "file_size": file_size,
        "chunk_size": chunk_size,
        "num_chunks": num_chunks,
        "file_hash": file_hash,
        "chunk_hashes": chunk_hashes
    }
    
    with open(output_meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=4, ensure_ascii=False)
        
    return metadata

def load_metadata(meta_path):
    """
    Carrega e retorna os metadados do arquivo JSON.
    """
    with open(meta_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def generate_random_file(file_path, size_bytes):
    """
    Gera um arquivo de teste contendo bytes aleatorios especificos de forma eficiente em memoria.
    """
    # Garante que a pasta pai existe
    parent_dir = os.path.dirname(file_path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
        
    # Escreve em blocos de 64KB para evitar sobrecarga de memoria
    block_size = 65536
    written = 0
    with open(file_path, 'wb') as f:
        while written < size_bytes:
            to_write = min(block_size, size_bytes - written)
            # Usando random.randbytes se disponivel (Python 3.9+) ou urandom
            f.write(os.urandom(to_write))
            written += to_write
