
import sys
import re
import os
import json
import xml.etree.ElementTree as ET

if getattr(sys, 'frozen', False):
    # Se estiver rodando como .exe, a raiz é a pasta onde o .exe está
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Se estiver no VS Code, a raiz é a pasta deste script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# =============================================================================
# PARSE
# =============================================================================

def parse_xml(file_obj):
    return ET.parse(file_obj).getroot()


def get_pi(obj):
    """Retorna dict {Name: Value} de todos os filhos PI do nó."""
    return {
        c.attrib.get('Name'): c.attrib.get('Value')
        for c in obj if c.tag == 'PI'
    }


def bitmask_to_bit_position(mask):
    """
    Converte BitMask numérico para posição de bit (0-based).

    Exemplos:
        BitMask=1  → bit 0
        BitMask=2  → bit 1
        BitMask=4  → bit 2
        BitMask=8  → bit 3

    Retorna None se:
        - mask for None ou não numérico
        - mask for 0 ou negativo
        - mask não for potência de 2 (bitmask inválido para bit único)
    """
    try:
        v = int(mask)
    except (TypeError, ValueError):
        return None

    if v <= 0 or (v & (v - 1)) != 0:
        return None

    return v.bit_length() - 1


def _is_binary_type(ctype: str) -> bool:
    """
    Retorna True se o TYPE do ponto indica BinaryInput ou BinaryOutput.

    Comparação case-insensitive. Cobre variações do EBO:
        modbus.point.binaryinput
        modbus.point.binaryoutput
        modbus.point.binary.input   (variações com ponto)
        modbus.point.binary.output
    """
    ct = ctype.lower()
    return (
        'binaryinput'  in ct or
        'binaryoutput' in ct or
        'binary.input' in ct or
        'binary.output' in ct
    )


# =============================================================================
# EXTRAÇÃO
# =============================================================================

def extract_data(root):
    networks = []
    points   = []
    avisos   = []

    # Rastreia nós de rede já visitados para evitar duplicatas
    visited_networks = set()

    def traverse(node, ancestors=None):
        """
        Percorre a árvore XML recursivamente.

        `ancestors` é a lista de nós ancestrais do mais distante para o mais
        próximo. O pai direto do modbus.network é sempre ancestors[-1], o que
        evita que pastas-container de nível superior (ex: "Panels") sejam
        usadas como root do ponto.
        """
        if ancestors is None:
            ancestors = []

        obj_type = node.attrib.get('TYPE', '').lower()
        obj_name = node.attrib.get('NAME', '')

        if 'modbus.network' in obj_type and 'masterdevice' not in obj_type:
            network_id = id(node)

            if network_id in visited_networks:
                # Rede já processada: apenas desce nos filhos e retorna
                for child in node:
                    traverse(child, ancestors + [node])
                return
            visited_networks.add(network_id)

            pi           = get_pi(node)
            ip           = pi.get('IPAddress')
            network_name = obj_name
            equipamento = network_name

            # unit_id: lê do atributo DESCR do nó (não do PI)
            unit_id   = 1
            raw_descr = node.attrib.get('DESCR', '').strip()
            if raw_descr.isdigit():
                unit_id = int(raw_descr)

            if ip:
                networks.append({
                    "root":    equipamento,
                    "name":    network_name,
                    "ip":      ip,
                    "unit_id": unit_id,
                })
            else:
                avisos.append(f"Rede '{network_name}' (equipamento '{equipamento}') sem IPAddress — ignorada")

            def scan_points(n, uid, net_name = None):
                """
                Varre recursivamente todos os pontos Modbus dentro de `n`.
                """
                current_net = net_name if net_name is not None else network_name
                for child in n:
                    ctype = child.attrib.get('TYPE', '').lower()

                    if 'modbus.point' in ctype:
                        pi_child = get_pi(child)
                        reg      = pi_child.get('RegisterNumber')
                        read_fc  = pi_child.get('ReadFunctionCode')

                        if read_fc is None and _is_binary_type(ctype):
                            read_fc = '2'

                        if reg and reg.isdigit():
                            # Posição de bit (None se BitMask ausente ou inválido)
                            bit = bitmask_to_bit_position(pi_child.get('BitMask'))
                            is_binary = _is_binary_type(ctype)

                            points.append({
                                "root":          equipamento,
                                "network":       current_net,
                                "name":          child.attrib.get('NAME'),
                                "register":      reg,
                                "function":      read_fc,
                                "register_type": pi_child.get('RegisterType'),
                                "bit":           bit,
                                "unit_id":       uid,
                                "is_binary":     is_binary,   # NOVO
                            })
                        # else:
                        #     point_name = child.attrib.get('NAME', 'sem nome')
                        #     avisos.append(f"Ponto '{point_name}' na rede '{network_name}' sem RegisterNumber válido — ignorado")

                    # Desce em filhos que NÃO sejam outra modbus.network.
                    # Inclui qualquer agrupador lógico (folders, groups, panels).

                    if 'masterdevice' in ctype:
                        sub_descr = child.attrib.get('DESCR', '').strip()
                        sub_uid   = int(sub_descr) if sub_descr.isdigit() else uid
                        sub_net   = child.attrib.get('NAME', current_net)
                        scan_points(child, sub_uid, sub_net)

                    elif 'modbus.network' not in ctype:
                        scan_points(child, uid, current_net)


            scan_points(node, unit_id)
            
            
        
        # Continua a travessia para os filhos com lista de ancestrais atualizada
        for child in node:
            traverse(child, ancestors + [node])

    traverse(root)

    # Diagnóstico
    binarios  = sum(1 for p in points if p.get('is_binary'))
    analogicos = len(points) - binarios
    print(f"🔎 {len(points)} pontos encontrados  "
          f"({analogicos} analógicos, {binarios} binários)")

    return networks, points, avisos


# =============================================================================
# GERAÇÃO DO DOCKER-COMPOSE
# =============================================================================

def generate_compose(devices):
    """Gera docker-compose.yml — lógica inalterada."""
    lines = ["services:"]

    for d in devices:
        name = re.sub(r'[^a-zA-Z0-9]+', '-', d["name"]).strip('-').lower()

        lines += [
            f"  {name}:",
            f"    build: .",
            f"    container_name: {name}",
            f"    ports:",
            f"      - \"{d['ip']}:502:502\"",
            f"    restart: always",
            f"    volumes:",
            f"      - /var/run/docker.sock:/var/run/docker.sock",
            f"      - ./:/app",
        ]
    compose_path = os.path.join(BASE_DIR, "docker-compose.yml")
    with open(compose_path, "w") as f:
        f.write("\n".join(lines))


# =============================================================================
# GERAÇÃO DO MOCK
# =============================================================================
def generate_mock(points):
    """
    Gera modbus_mock_data.json de forma dinâmica.
    Compatível com execução em formato .exe (contorna o cache de importação do Python).
    """
    # Estrutura base do JSON
    mock_data = {
        "MOCK_REGISTERS": [],
        "MOCK_STRUCTURE": {}
    }

    for p in points:
        r         = p['root']
        n         = p['network']
        nome      = p['name']
        unit_id   = p.get('unit_id', 1)
        is_binary = p.get('is_binary', False)

        # Ignora root inválido
        if not r or str(r).lower() == "none":
            continue

        # Alinha exatamente com os 9 campos que o seu server.py desempacota
        # (O Python lê listas JSON exatamente como se fossem tuplas no desempacotamento)
        mock_data["MOCK_REGISTERS"].append([
            r,                          # 0: root
            n,                          # 1: network
            int(p['register']),         # 2: register
            p['function'],              # 3: function
            p['register_type'],         # 4: register_type
            p['bit'],                   # 5: bit (None vira null no JSON, que vira None no Python)
            nome,                       # 6: name
            unit_id,                    # 7: unit_id
            is_binary                   # 8: is_binary
        ])

        # Cria a árvore de estrutura para a interface gráfica
        mock_data["MOCK_STRUCTURE"].setdefault(r, {})
        mock_data["MOCK_STRUCTURE"][r].setdefault(n, {"unit_id": unit_id, "points": []})

        if nome not in mock_data["MOCK_STRUCTURE"][r][n]["points"]:
            mock_data["MOCK_STRUCTURE"][r][n]["points"].append(nome)

    # Define o caminho absoluto ao lado do .exe
    json_path = os.path.join(BASE_DIR, "modbus_mock_data.json")

    # Grava o arquivo JSON no disco
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, indent=4, ensure_ascii=False)

    n_bin = sum(1 for p in points if p.get('is_binary') and not (not p['root'] or str(p['root']).lower() == "none"))
    print(f"✅ JSON gerado com {len(mock_data['MOCK_STRUCTURE'])} equipamentos "
          f"({len(points) - n_bin} analógicos, {n_bin} binários)")
    

# =============================================================================
# INTERFACE FLASK / CLI
# =============================================================================

def process_xml(file_obj):
    root = parse_xml(file_obj)
    devices, points, avisos = extract_data(root)
    generate_compose(devices)
    generate_mock(points)
    return devices, points, avisos


def main():
    if len(sys.argv) < 2:
        print("Uso: python modbus_xml_parser.py arquivo.xml")
        return

    xml_path = sys.argv[1]

    if not os.path.exists(xml_path):
        print("Arquivo não encontrado")
        return

    with open(xml_path, "rb") as f:
        process_xml(f)


if __name__ == "__main__":
    main()