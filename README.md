# Compartilhamento de Arquivos Peer-to-Peer (P2P) - CEFET-MG

Este repositório contém o código-fonte desenvolvido para o **Trabalho Prático 2** da disciplina de **Sistemas Distribuídos** do Centro Federal de Educação Tecnológica de Minas Gerais (CEFET-MG), período letivo 2025/2.

O objetivo do projeto é a criação de um sistema simétrico e descentralizado de compartilhamento de arquivos P2P baseado em Sockets TCP multithreading em Python.

---

## 👥 Integrantes do Grupo

*   **Marcos Silva** (Campus II - DECOM)
*   **Arthur Bracarense** (Campus II - DECOM)

**Professora:** Michelle Hanne

---

## 🚀 Arquitetura e Decisões de Projeto

O sistema opera de forma puramente descentralizada, sem o uso de servidores centrais (Trackers) ou de coordenação externa. Toda a topologia da rede é estática e pré-configurada nos parâmetros de execução de cada nó.

### Principais Características Técnicas:
1.  **Sincronização Simétrica Concorrente:** Cada nó inicia simultaneamente uma thread servidor TCP (escutando requisições na porta especificada) e conexões clientes dedicadas para cada nó vizinho.
2.  **Delimitação de Mensagens (TCP Framing):** Toda mensagem é precedida por um cabeçalho binário de 4 bytes contendo o tamanho do corpo da mensagem. Isso contorna problemas de coalescência ou truncamento do fluxo de bytes nativo do TCP.
3.  **HAVE Broadcasts:** Sempre que um bloco é recebido e validado com sucesso, uma mensagem do tipo `HAVE` é enviada em broadcast para todos os vizinhos conectados. Isso possibilita que os vizinhos comecem a baixar partes do arquivo desse peer antes mesmo de ele ter concluído o download do arquivo inteiro (compartilhamento progressivo).
4.  **Escrita Otimizada com seek():** Ao iniciar, os leechers criam um arquivo pre-alocado preenchido com zeros em disco. À medida que os blocos chegam, são escritos na posição física correta do arquivo binário utilizando a chamada `seek(index * chunk_size)`, eliminando o consumo excessivo de memória RAM por manter o arquivo completo em buffers de execução.
5.  **Validação Dupla via SHA-256:** Cada pedaço binário é verificado individualmente contra a tabela de hashes contida no metadado JSON logo após ser baixado. No fim da transferência, o arquivo completo remontado é validado contra o hash global, mitigando riscos de corrupção.

---

## 📂 Estrutura de Arquivos

*   `src/peer.py`: Implementação da lógica principal do nó peer (módulos cliente/servidor multithread, controle de bitfields e o protocolo de pacotes).
*   `src/utils.py`: Funções utilitárias de hash SHA-256, fatiamento/remontagem física e geração de metadados JSON.
*   `test_runner.py`: Script automatizado para simular concorrentemente os 6 cenários de rede exigidos no enunciado do trabalho (Tabela 1).
*   `generate_report.py`: Script auxiliar usado para processar os resultados e gerar automaticamente o relatório de desempenho formatado.
*   `requirements.txt`: Dependência de PDF (`fpdf2`).

---

## 🛠️ Como Executar os Testes

Para instalar a biblioteca de geração de relatório:
```bash
pip install -r requirements.txt
```

### Rodando o Benchmarking em Lote (Cenários 1 a 6)
O script de automação de testes criará arquivos binários aleatórios (de 10 KB a 20 MB), gerará os metadados na pasta temporária, inicializará os processos concorrentes e validará a integridade global em loopback local:
```bash
python test_runner.py
```
Isso produzirá o arquivo `test_results.json` contendo as velocidades e durações de cada nó na rede local.
