
EBO DEVICE SIMULATOR

-------------------------------------------------------------------------------
COMO UTILIZAR
-------------------------------------------------------------------------------

1. Abra o sistema.

2. Abra o Docker.desktop.

3. Deixe a placa de rede "Ethernet" ativa.

4. Na tela inicial, importe o arquivo XML:
   - clicando na área de upload;
   - ou arrastando o arquivo para a tela.

5. Após a importação, o sistema iniciará automaticamente o rebuild dos
   containers Docker.

6. Aguarde a mensagem de conclusão do rebuild.

7. Após finalizar, será exibida a árvore de navegação contendo:
   - networks;
   - devices;
   - pontos analógicos;
   - pontos binários.

-------------------------------------------------------------------------------
NAVEGAÇÃO
-------------------------------------------------------------------------------

A barra lateral esquerda possui:

- campo de pesquisa para localizar pontos;
- botão para recolher toda a árvore;
- botão “Binário” para selecionar todos os pontos binários;
- botão “Analógico” para selecionar todos os pontos analógicos.

Ao clicar em um item da árvore, sua estrutura será expandida.

-------------------------------------------------------------------------------
SELEÇÃO DE PONTOS
-------------------------------------------------------------------------------

O sistema suporta:

- seleção individual;
- seleção múltipla;
- envio simultâneo de valores.

Métodos de seleção:
- clique simples;
- checkbox;
- Ctrl + Clique;
- Shift + seleção por área.

-------------------------------------------------------------------------------
ENVIO DE VALORES
-------------------------------------------------------------------------------

Ao selecionar um ponto, será exibida a área de envio de valores.

O sistema suporta:
- valores analógicos;
- valores binários;
- escrita por bit;
- escrita em lote;
- múltiplos Unit IDs.

Também é possível enviar o mesmo valor para vários pontos ao mesmo tempo.

-------------------------------------------------------------------------------
AUDITORIA
-------------------------------------------------------------------------------

Todas as operações realizadas são registradas automaticamente.

O sistema gera:
- relatório PDF;
- relatório XLSX.

-------------------------------------------------------------------------------
DOWNLOAD DOS RELATÓRIOS
-------------------------------------------------------------------------------

Após finalizar os testes:

1. Clique no botão de download localizado no canto superior direito.

2. Escolha o formato desejado:
   - PDF;
   - XLSX.

-------------------------------------------------------------------------------
PROBLEMAS COMUNS
-------------------------------------------------------------------------------

Containers não iniciam:
- verificar se o Docker Desktop está aberto.

Erro na porta 502:
- outra aplicação Modbus está utilizando a porta.

XML não carrega:
- verificar se o arquivo está válido.

Pontos não respondem:
- verificar IP, Unit ID e configuração do ponto.

Docker não inicia:
- Conecte e desconecte o cabo de rede, reativando a placa "Ethernet".

Gateway Modbus não comunica
- No EBO em Enable communication desative e reative de novo a comunicação.

-------------------------------------------------------------------------------
OBSERVAÇÕES
-------------------------------------------------------------------------------

- O Docker deve permanecer aberto durante toda a utilização.
- O rebuild pode levar alguns segundos dependendo da quantidade de pontos.
- Recomenda-se salvar os relatórios após finalizar os testes.
```
