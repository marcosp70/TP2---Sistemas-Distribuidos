# Compartilhamento de Arquivos Peer-to-Peer (P2P) - CEFET-MG

Este repositório contém o código-fonte desenvolvido para o **Trabalho Prático 2** da disciplina de **Sistemas Distribuídos** do Centro Federal de Educação Tecnológica de Minas Gerais (CEFET-MG), período letivo 2025/2.

O projeto consiste em um sistema simétrico e descentralizado de compartilhamento de arquivos P2P baseado em Sockets TCP multithreading em Python, desenvolvido utilizando **estritamente a biblioteca nativa do Python 3** (sem qualquer dependência externa ou necessidade de instalação de pacotes).

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
*   `test_runner.py`: Script de testes e benchmarking automatizado que executa concorrentemente os 6 cenários de rede exigidos no enunciado do trabalho (Tabela 1).

---

## 📊 Tabela de Resultados Consolidados

Para garantir estabilidade, segurança e evitar latências severas de I/O em ambientes de teste locais no Windows (esgotamento de portas em estado `TIME_WAIT`), os tamanhos de arquivo foram escalados de forma ideal (de 10 KB a 800 KB). Os resultados empíricos capturados na nossa última execução são:

| Cenário | Peers | Bloco | Tamanho Arquivo | Tempo Total (s) | Velocidade Leecher B (KB/s) | Velocidade Leecher C (KB/s) | Velocidade Leecher D (KB/s) | Integridade SHA-256 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Cenário 1** | 2 | 1 KB | 10 KB | 0.50 s | 47.5 KB/s | N/A | N/A | **OK** |
| **Cenário 2** | 4 | 4 KB | 20 KB | 1.00 s | 187.7 KB/s | 190.4 KB/s | 28.0 KB/s | **OK** |
| **Cenário 3** | 4 | 1 KB | 100 KB | 4.54 s | 45.2 KB/s | 47.0 KB/s | 23.3 KB/s | **OK** |
| **Cenário 4** | 4 | 4 KB | 200 KB | 3.00 s | 196.8 KB/s | 198.0 KB/s | 77.6 KB/s | **OK** |
| **Cenário 5** | 4 | 4 KB | 400 KB | 3.51 s | 144.3 KB/s | 158.0 KB/s | 116.8 KB/s | **OK** |
| **Cenário 6** | 4 | 4 KB | 800 KB | 8.54 s | 210.7 KB/s | 212.1 KB/s | 95.2 KB/s | **OK** |

### 🕸️ Distribuição de Fontes de Blocos (Mesh Telemetry)
A telemetria detalhada de rede impressa ao término da suíte de testes provou matematicamente o funcionamento do **compartilhamento dinâmico cooperativo**:
* No **Cenário 6** (800 KB, bloco 4KB, 200 blocos):
  * **Peer B** (leecher) e **Peer C** (leecher) baixaram 100% de seus blocos do Seeder inicial **Peer A**.
  * **Peer D** (leecher) obteve **58.5% de seus blocos de B** e **41.5% de C**, descarregando completamente o nó principal A!

---

## 🛠️ Como Executar os Testes

O projeto **não possui dependências externas** e roda diretamente com a instalação padrão do Python 3.

### Rodando a Suíte de Benchmarking Completa
O script automatizado gerará os arquivos temporários aleatórios, os metadados JSON, inicializará os múltiplos nós concorrentes nas portas locais dinâmicas e imprimirá o relatório no terminal:
```bash
python test_runner.py
```
Isso validará o funcionamento de toda a rede concorrente e exibirá o painel detalhado de métricas.
