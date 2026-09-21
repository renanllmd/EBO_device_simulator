# EBO Device Simulator

Simulador de dispositivos e pontos para testes de comunicação e integração com ambientes Modbus.

O **EBO Device Simulator** permite importar arquivos XML, visualizar a estrutura de redes e dispositivos, selecionar pontos analógicos e binários e realizar o envio de valores para os pontos selecionados.

As operações realizadas durante os testes também podem ser registradas e exportadas em relatórios PDF e XLSX.

---

## Funcionalidades

- Importação de arquivos XML por upload ou arrastar e soltar.
- Leitura e organização da estrutura de:
  - Networks;
  - Devices;
  - Pontos analógicos;
  - Pontos binários.
- Pesquisa de pontos.
- Expansão e recolhimento da árvore de dispositivos.
- Seleção individual ou múltipla de pontos.
- Seleção por `Ctrl + Clique`.
- Seleção por área utilizando `Shift`.
- Seleção rápida de pontos binários.
- Seleção rápida de pontos analógicos.
- Envio de valores analógicos.
- Envio de valores binários.
- Escrita por bit.
- Escrita em lote.
- Envio simultâneo para múltiplos Unit IDs.
- Registro das operações realizadas durante os testes.
- Geração de relatórios em PDF.
- Geração de relatórios em XLSX.
- Integração com containers Docker.

---

## Requisitos

Antes de iniciar o sistema, certifique-se de que os seguintes requisitos estejam disponíveis:

- Windows
- Docker Desktop
- Placa de rede `Ethernet` ativa
- Arquivo XML compatível com o simulador

> O Docker Desktop deve permanecer aberto durante toda a utilização do sistema.

---

## Como utilizar

### 1. Inicie o sistema

Abra o **EBO Device Simulator**.

### 2. Inicie o Docker Desktop

Abra o **Docker Desktop** e aguarde até que o serviço esteja em execução.

### 3. Verifique a placa de rede

Certifique-se de que a placa de rede **Ethernet** esteja ativa.

### 4. Importe o arquivo XML

Na tela inicial, importe o arquivo XML utilizando uma das opções:

- Clique na área de upload e selecione o arquivo.
- Arraste o arquivo XML diretamente para a área de upload.

### 5. Aguarde o rebuild

Após a importação do XML, o sistema iniciará automaticamente o processo de **rebuild dos containers Docker**.

Aguarde até que seja exibida a mensagem informando que o processo foi concluído.

> O tempo de rebuild pode variar de acordo com a quantidade de pontos presentes no arquivo XML.

### 6. Visualize os dispositivos

Após a conclusão do rebuild, será apresentada a árvore de navegação contendo:

```text
Networks
└── Devices
    ├── Pontos analógicos
    └── Pontos binários
