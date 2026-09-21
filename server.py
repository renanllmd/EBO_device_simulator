import threading
import struct
import re
import yaml
import sys
import time
import subprocess
import os
import json
import webbrowser
from threading import Timer
if getattr(sys, 'frozen', False):
    # Se estiver rodando como .exe, a raiz é a pasta onde o .exe está
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Se estiver no VS Code, a raiz é a pasta deste script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Força o Python a buscar arquivos .py externos na pasta do executável
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from openpyxl import Workbook, load_workbook
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
from modbus_xml_parser import parse_xml, extract_data, generate_mock, generate_compose
from pymodbus.server.sync import StartTcpServer
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext, ModbusSparseDataBlock
from pymodbus.client.sync import ModbusTcpClient
from ip_config import sincronizar_ips_ethernet
from auditoria import ExcelLogger

MOCK_REGISTERS = []
MOCK_STRUCTURE = {}

def load_mock_data():
    """
    Lê o arquivo JSON do disco e atualiza as variáveis globais na memória instantaneamente.
    Pode ser chamada no início do programa e sempre que um novo upload for feito.
    """
    global MOCK_REGISTERS, MOCK_STRUCTURE
    
    json_path = os.path.join(BASE_DIR, "modbus_mock_data.json")
    
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                dados = json.load(f)
                MOCK_REGISTERS = dados.get("MOCK_REGISTERS", []) or []
                MOCK_STRUCTURE = dados.get("MOCK_STRUCTURE", {}) or {}
            print(f"🔄 Dados Modbus atualizados com sucesso! ({len(MOCK_REGISTERS)} pontos em memória)")
        except Exception as e:
            print(f"❌ Erro ao ler o arquivo JSON: {e}")
    else:
        # Valores padrão vazios caso o usuário ainda não tenha feito upload de nenhum XML
        MOCK_REGISTERS = []
        MOCK_STRUCTURE = {}
        print("⚠️ Nenhum arquivo modbus_mock_data.json encontrado. Aguardando upload do XML...")

# Carrega os dados assim que o servidor inicia
load_mock_data()

# =============================================================================
# INICIALIZAÇÃO GLOBAL
# =============================================================================

ip_map       = {}
excel_logger = ExcelLogger(BASE_DIR)


def carregar_ip_map():
    global ip_map
    ip_map = {}
    compose_path = os.path.join(BASE_DIR, 'docker-compose.yml')
    if not os.path.exists(compose_path):
        return
    with open(compose_path, 'r') as f:
        compose = yaml.safe_load(f)
    if not compose or not isinstance(compose, dict):
        print("⚠️ docker-compose.yml vazio ou inválido, ip_map não carregado.")
        return
    
    for svc_name, svc in (compose.get('services') or {}).items():
        for port in (svc or {}).get('ports') or []:
            if not port or ':' not in str(port):
                continue
            ip = str(port).split(':')[0]
            ip_map[svc_name.upper()] = ip
            cname = svc.get('container_name', '')
            if cname:
                ip_map[cname.upper()] = ip


carregar_ip_map()


# =============================================================================
# DOCKER
# =============================================================================

def disparar_launcher():
    try:
        print("Compose atualizado, disparando rebuild...")
        compose_file = os.path.join(BASE_DIR, "docker-compose.yml")
        comandos = [
             f"docker compose -f \"{compose_file}\" build --no-cache",
             f"docker compose -f \"{compose_file}\" up -d --build"

        ]
        for cmd in comandos:
            resultado = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            print(resultado.stdout)
            if resultado.returncode != 0:
                print(f"Erro: {resultado.stderr}")

        print("\n[DOCKER] Aguardando containers inicializarem...")
        print("\n[DOCKER] Rebuild concluído.")

    except Exception as e:
        print(f"Erro no rebuild: {e}")


# =============================================================================
# UTILITÁRIOS MODBUS
# =============================================================================

def normalizar_nome_container(nome):
    if not nome:
        return None
    return re.sub(r'[^a-zA-Z0-9]+', '-', str(nome)).strip('-').upper()


def network_para_ip(network=None, root=None):
    candidatos = []

    if network:
        candidatos.extend([
            network,
            normalizar_nome_container(network)
        ])

    if root:
        candidatos.extend([
            root,
            normalizar_nome_container(root)
        ])

    for item in candidatos:
        if not item:
            continue
        key = str(item).upper()
        if key in ip_map:
            return ip_map[key]

    return None


def ajustar_offset(address, fc_raw=3):
    return int(address) - 1


def tamanho_tipo(tipo_int):
    if tipo_int in [3, 4, 5, 6, 7, 8, 11, 12, 13]:
        return 2
    elif tipo_int in [9, 10, 16, 17, 18, 19, 20, 21]:
        return 4
    elif tipo_int in [14, 15]:
        return 3
    return 1


def valor_para_registradores(valor, tipo):
    try:
        tipo = int(tipo)
    except (TypeError, ValueError):
        tipo = 1

    if tipo == 1:   # 16 bit unsigned
        return [int(valor) & 0xFFFF]

    elif tipo == 2: # 16 bit signed
        return [int(valor) & 0xFFFF]

    elif tipo == 3: # 32 bit unsigned
        v = int(valor) & 0xFFFFFFFF
        packed = struct.pack('>I', v)
        hi, lo = struct.unpack('>HH', packed)
        return [lo, hi]

    elif tipo == 4: # 32 bit unsigned swapped
        v = int(valor) & 0xFFFFFFFF
        packed = struct.pack('>I', v)
        hi, lo = struct.unpack('>HH', packed)
        return [hi, lo]

    elif tipo == 5: # 32 bit signed
        packed = struct.pack('>i', int(valor))
        hi, lo = struct.unpack('>HH', packed)
        return [lo, hi]

    elif tipo == 6: # 32 bit signed swapped
        packed = struct.pack('>i', int(valor))
        hi, lo = struct.unpack('>HH', packed)
        return [hi, lo]

    elif tipo == 7: # 32 bit real
        packed = struct.pack('>f', float(valor))
        hi, lo = struct.unpack('>HH', packed)
        return [lo, hi]

    elif tipo == 8: # 32 bit real swapped
        packed = struct.pack('>f', float(valor))
        return list(struct.unpack('>HH', packed))

    elif tipo == 9: # 64 bit real
        packed = struct.pack('>d', float(valor))
        w1, w2, w3, w4 = struct.unpack('>HHHH', packed)
        return [w4, w3, w2, w1]

    elif tipo == 10: # 64 bit real swapped
        packed = struct.pack('>d', float(valor))
        return list(struct.unpack('>HHHH', packed))

    elif tipo == 11: # 32 bit unsigned MOD10K
        v = int(valor) & 0xFFFFFFFF
        return [v % 10000, v // 10000]

    elif tipo == 12: # 32 bit unsigned MOD10K swapped
        v = int(valor) & 0xFFFFFFFF
        return [v // 10000, v % 10000]

    elif tipo == 13: # 32 bit signed MOD10K
        v = int(valor)
        return [v % 10000, v // 10000]

    elif tipo == 14: # 48 bit unsigned MOD10K
        v = int(valor) & 0xFFFFFFFFFFFF
        r2 = v // 10 ** 8
        r1 = (v // 10 ** 4) % 10000
        r0 = v % 10000
        return [r0, r1, r2]

    elif tipo == 15: # 48 bit unsigned MOD10K swapped
        v = int(valor) & 0xFFFFFFFFFFFF
        r2 = v // 10 ** 8
        r1 = (v // 10 ** 4) % 10000
        r0 = v % 10000
        return [r2, r1, r0]

    elif tipo == 16: # 64 bit unsigned MOD10K
        v = int(valor) & 0xFFFFFFFFFFFFFFFF
        r3 = v // 10 ** 12
        r2 = (v // 10 ** 8) % 10000
        r1 = (v // 10 ** 4) % 10000
        r0 = v % 10000
        return [r0, r1, r2, r3]

    elif tipo == 17: # 64 bit unsigned MOD10K swapped
        v = int(valor) & 0xFFFFFFFFFFFFFFFF
        r3 = v // 10 ** 12
        r2 = (v // 10 ** 8) % 10000
        r1 = (v // 10 ** 4) % 10000
        r0 = v % 10000
        return [r3, r2, r1, r0]

    elif tipo == 18: # 64 bit unsigned
        v = int(valor) & 0xFFFFFFFFFFFFFFFF
        packed = struct.pack('>Q', v)
        w1, w2, w3, w4 = struct.unpack('>HHHH', packed)
        return [w4, w3, w2, w1]

    elif tipo == 19: # 64 bit unsigned swapped
        v = int(valor) & 0xFFFFFFFFFFFFFFFF
        packed = struct.pack('>Q', v)
        w1, w2, w3, w4 = struct.unpack('>HHHH', packed)
        return [w1, w2, w3, w4]

    elif tipo == 20: # 64 bit signed
        packed = struct.pack('>q', int(valor))
        w1, w2, w3, w4 = struct.unpack('>HHHH', packed)
        return [w4, w3, w2, w1]

    elif tipo == 21: # 64 bit signed swapped
        packed = struct.pack('>q', int(valor))
        w1, w2, w3, w4 = struct.unpack('>HHHH', packed)
        return [w1, w2, w3, w4]

    return [int(valor) & 0xFFFF]


def dict_para_bloco_continuo(d):
    if not d:
        return ModbusSparseDataBlock({0: 0})
    min_addr = min(d.keys())
    max_addr = max(d.keys())
    bloco = {addr: 0 for addr in range(min_addr, max_addr + 5)}
    bloco.update(d)
    return ModbusSparseDataBlock(bloco)


# =============================================================================
# ESTADO MODBUS GLOBAL
# =============================================================================

hr_dict  = {}
co_dict  = {}
di_dict  = {}
name_map = {}
context  = None


def rebuild_modbus_data():
    global hr_dict, co_dict, di_dict, name_map, context 
    avisos_rebuild = []

    hr_dict  = {}
    co_dict  = {}
    di_dict  = {}
    name_map = {}

    for row in MOCK_REGISTERS:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            continue
        root, net, address, function, tipo, bit, nome, *_extra = row
        unit_id   = _extra[0] if len(_extra) > 0 else None
        is_binary = bool(_extra[1]) if len(_extra) > 1 else False

        try:
            fc_raw = int(function) #type: ignore
        except (TypeError, ValueError):
            fc_raw = 3

        try:
            addr = ajustar_offset(int(address), fc_raw)
        except (TypeError, ValueError):
            continue

        tipo_int = 1
        try:
            tipo_int = int(tipo)#type: ignore
        except (TypeError, ValueError):
            pass

        size = tamanho_tipo(tipo_int)

        if fc_raw == 1:
            for i in range(size):
                co_dict[addr + 1 + i] = 0
        # elif fc_raw == 2:
        #     for i in range(size):
        #         co_dict[addr + 1 + i] = 0
        else:
            for i in range(size):
                    hr_dict[addr + i] = 0

        bit_val = None
        if bit not in [None, "None", ""]:
            try:
                bit_val = int(bit)#type: ignore
            except (TypeError, ValueError):
                pass

        name_map[(root, net, nome)] = {
            "addr":        addr,
            "raw_address": int(address),
            "tipo":        tipo_int,
            "fc":          3 if fc_raw in [2, 3, 4] else fc_raw,
            "fc_raw":      fc_raw,
            "bit":         bit_val,
            "size":        size,
            "unit_id":     unit_id,
            "is_binary":   is_binary,   
        }

    # Coleta unit_ids únicos
    unit_ids = set()
    for info in name_map.values():
        uid = info.get("unit_id")
        if uid is not None:
            try:
                unit_ids.add(int(uid))
            except (TypeError, ValueError):
                pass
    if not unit_ids:
        unit_ids = {1}

    slaves = {}
    for uid in unit_ids:
        hr_block = dict_para_bloco_continuo(dict(hr_dict) if hr_dict else {0: 0})
        co_block = dict_para_bloco_continuo(dict(co_dict) if co_dict else {0: 0})

        slaves[uid] = ModbusSlaveContext(
            hr=hr_block,
            ir=hr_block,   
            di=hr_block,
            co=co_block   
        )

    context = ModbusServerContext(slaves=slaves, single=False)
    print("Rebuild modbusdata")
    # print("co_dict:", co_dict)
    #  print("di_dict:", di_dict)
    # print("hr_dict", hr_dict)
    return avisos_rebuild


rebuild_modbus_data()


# =============================================================================
# ÁRVORE DE PONTOS
# =============================================================================

def build_tree_from_mock():
    tree = []
    for root_name, networks in MOCK_STRUCTURE.items():
        root_node = {"label": root_name, "children": []}
        if not isinstance(networks, dict):
            continue
        for network_name, net_data in networks.items():
            points = net_data["points"] if isinstance(net_data, dict) else net_data
            network_node = {"label": network_name, "children": []}
            for point_name in points:
                info = name_map.get((root_name, network_name, point_name), {})
                network_node["children"].append({
                    "root":          root_name,
                    "network":       network_name,
                    "name":          point_name,
                    "register":      info.get("raw_address"),
                    "register_type": info.get("tipo"),
                    "bit":           info.get("bit"),
                    "fc":            info.get("fc_raw"),
                    "unit_id":       info.get("unit_id", 1),
                    "is_binary":     info.get("is_binary", False),  # exposto na árvore
                })
            root_node["children"].append(network_node)
        tree.append(root_node)
    print("Rebuild tree from mock")
    return tree


# =============================================================================
# ESCRITA MODBUS
# =============================================================================

def _valor_binario_para_int(valor_str) -> int:
    return 1 if str(valor_str).strip().lower() in {"1", "true", "on", "yes"} else 0


def escrever_via_tcp(ip, addr, fc, bit=None, valor_str=None, tipo=None,
                     unit_id=1, is_binary=False):
    """
    Escreve um ponto via conexão TCP direta ao container/dispositivo.

    CORREÇÃO [2] + [3]: parâmetro `is_binary` adicionado.
    Quando is_binary=True e bit=None, escreve 0/1 direto no registrador
    em vez de passar por valor_para_registradores().
    """
    client = ModbusTcpClient(ip, port=502, timeout=3)
    if not client.connect():
        return False, f"Não foi possível conectar em {ip}:502"

    try:
        try:
            uid = int(unit_id) if unit_id is not None else 1
        except (TypeError, ValueError):
            uid = 1

        # --- FC1/FC2: coils e discrete inputs ---
        if fc == 1:
            novo = _valor_binario_para_int(valor_str)
            if bit is not None:
                endereco_final = addr + bit
                client.write_coil(endereco_final, bool(novo), unit=uid)
                estado = "TRUE" if novo else "FALSE"
                msg = (f"✅ COIL BIT{bit} = {estado} "
                       f"addr {addr}+{bit}={endereco_final} ID = {uid} via {ip}")
            else:
                client.write_coil(addr, bool(novo), unit=uid)
                msg = f"✅ COIL = {bool(novo)} (addr {addr}) ID = {uid} via {ip}"
 
        # --- FC2: escreve via write_register (FC2 não tem write próprio no protocolo) ---
        elif fc == 2:
            if bit is not None:
                result = client.read_holding_registers(addr, 1, unit=uid)
                atual  = 0 if result.isError() else result.registers[0]
                novo_bit = _valor_binario_para_int(valor_str)
                if novo_bit:
                    valor_final = atual | (1 << bit)
                    estado = "TRUE"
                else:
                    valor_final = atual & ~(1 << bit)
                    estado = "FALSE"
                client.write_register(addr, valor_final, unit=uid)
                msg = f"✅ FC2 BIT{bit} = {estado} registro {addr} -> {valor_final} ID = {uid} via {ip}"
            elif is_binary:
                novo = _valor_binario_para_int(valor_str)
                client.write_register(addr, novo, unit=uid)
                msg = f"✅ FC2 BIN = {novo} registro {addr} ID = {uid} via {ip}"
            else:
                regs = valor_para_registradores(valor_str, tipo)
                if len(regs) == 1:
                    client.write_register(addr, regs[0], unit=uid)
                else:
                    client.write_registers(addr, regs, unit=uid)
                msg = f"✅ FC2 Valor = {valor_str} registro {addr} tipo={tipo} ID = {uid} via {ip}"
 
        elif is_binary and bit is None:
            novo = _valor_binario_para_int(valor_str)
            client.write_register(addr, novo, unit=uid)
            msg = f"✅ BIN_REG = {novo} registro {addr} ID = {uid} via {ip}"

        # --- Bitmask em holding register ---
        elif bit is not None:
            result = client.read_holding_registers(addr, 1, unit=uid)
            atual  = 0 if result.isError() else result.registers[0]
            if _valor_binario_para_int(valor_str):
                novo   = atual | (1 << bit)
                estado = "TRUE"
            else:
                novo   = atual & ~(1 << bit)
                estado = "FALSE"
            client.write_register(addr, novo, unit=uid)
            msg = f"✅ BIT = {estado} registro {addr} -> {novo} ID = {uid} via {ip}"

        # --- Analógico ---
        else:
            regs = valor_para_registradores(valor_str, tipo)
            if len(regs) == 1:
                client.write_register(addr, regs[0], unit=uid)
            else:
                client.write_registers(addr, regs, unit=uid)
            msg = f"✅ Valor = {valor_str} registro = {addr} ID = {uid} via {ip}"

        print(msg)
        return True, msg

    except Exception as e:
        return False, str(e)

    finally:
        client.close()


def escrever_ponto(root, net, ponto, valor_str, unit_id=None):
    info = name_map.get((root, net, ponto))
    if info is None:
        return False, f"Ponto não encontrado: {root} / {net} / {ponto}"
 
    addr      = info["addr"]
    tipo      = info["tipo"]
    bit       = info["bit"]
    fc_raw    = info["fc_raw"]
    is_binary = info.get("is_binary", False)
 
    unit_id = unit_id if unit_id is not None else info.get("unit_id")
    try:
        unit_id = int(unit_id) if unit_id is not None else 1
    except (TypeError, ValueError):
        unit_id = 1
 
    # --- Rota TCP ---
    ip = network_para_ip(net, root)

    if not ip:
        msg = f"❌ IP não encontrado para '{net}' / '{root}' — container não mapeado ou XML não importado"
        return False, msg

    ok, msg = escrever_via_tcp(
        ip=ip, addr=addr, fc=fc_raw,
        bit=bit, valor_str=valor_str, tipo=tipo,
        unit_id=unit_id, is_binary=is_binary
    )
    if ok:
        excel_logger.adicionar_linha(root, net, ponto, addr, fc_raw, bit, ip, valor_str, msg)
    return ok, msg

# =============================================================================
# FLASK — API HTTP
# =============================================================================

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'),static_folder=os.path.join(BASE_DIR, 'static'))


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/upload-xml', methods=['POST'])
def upload_xml():
    if 'file' not in request.files and 'xml' not in request.files:
        return jsonify({"ok": False, "error": "Arquivo XML não enviado"}), 400
    file = request.files.get('file') or request.files.get('xml')
    if not file or file.filename == '':
        return jsonify({"ok": False, "error": "Arquivo inválido ou vazio"}), 400
    try:
        # xml_file = request.files['xml'] if 'xml' in request.files else file
        file.seek(0)
        root = parse_xml(file)
        devices, points, avisos = extract_data(root)
        compose_file = os.path.join(BASE_DIR, "docker-compose.yml")
        if os.path.exists(compose_file):
            subprocess.run(
                f'docker compose -f "{compose_file}" down',
                shell=True,
                capture_output=True,
                encoding='utf-8',
                errors='replace'
            )

        generate_compose(devices)
        generate_mock(points)

        sincronizar_ips_ethernet()

        load_mock_data()

        carregar_ip_map()
        avisos_rebuild = rebuild_modbus_data()
        avisos += avisos_rebuild
        tree = build_tree_from_mock()

        disparar_launcher()
        
        return jsonify({
            "ok":      True,
            "networks": len(devices),
            "points":   len(points),
            "tree":     tree,
            "avisos":   avisos
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "avisos": [str(e)]}), 500

@app.route('/set', methods=['POST'])
def api_set():
    data    = request.get_json(force=True)
    root    = data.get('root',    '')
    net     = data.get('net',     '')
    ponto   = data.get('ponto',   '')
    valor   = str(data.get('valor', '0'))
    unit_id = data.get('unit_id', '1')

    ok, msg = escrever_ponto(root, net, ponto, valor, unit_id=unit_id)
    return jsonify({"ok": ok, "msg": msg}), 200 if ok else 400


@app.route('/set-batch', methods=['POST'])
def api_set_batch():
    data            = request.get_json(force=True)
    analogicos      = data.get('analogicos', [])
    binarios        = data.get('binarios', [])
    valor_analogico = str(data.get('valor_analogico', '0'))
    valor_binario   = str(data.get('valor_binario', 'false')).lower()

    sucesso = 0
    falhas  = 0
    erros   = []

    # Validação dos valores de entrada
    val_bin_valido = valor_binario in ['true', 'false', '1', '0']

    val_ana_valido = True
    try:
        float(valor_analogico)
    except (ValueError, TypeError):
        val_ana_valido = False

    # ─── Processar analógicos ────────────────────────────────────────────────
    if val_ana_valido:
        for p in analogicos:
            root    = p.get('root', '')
            net     = p.get('net', '')
            ponto   = p.get('ponto', '')
            unit_id = p.get('unit_id', 1)

            info = name_map.get((root, net, ponto))

            if info:
                # CORREÇÃO [4]: binários não são analógicos, independente de fc
                if info.get('is_binary', False):
                    falhas += 1
                    erros.append(
                        f"{ponto}: ponto binário não aceita valor analógico"
                    )
                    continue

                # FC1/FC2 sem bit: coil/DI não aceita float
                if info.get('fc_raw') in [1, 2]:
                    falhas += 1
                    erros.append(
                        f"{ponto}: FC {info.get('fc_raw')} não aceita valor analógico"
                    )
                    continue

            ok, msg = escrever_ponto(root, net, ponto, valor_analogico, unit_id=unit_id)
            if ok:
                sucesso += 1
            else:
                falhas += 1
                erros.append(f"{ponto}: {msg}")
    else:
        falhas += len(analogicos)
        erros.append(f"Valor analógico inválido: {valor_analogico}")

    # ─── Processar binários ──────────────────────────────────────────────────
    if val_bin_valido:
        for p in binarios:
            root    = p.get('root', '')
            net     = p.get('net', '')
            ponto   = p.get('ponto', '')
            unit_id = p.get('unit_id', 1)

            info = name_map.get((root, net, ponto))

            if info:
                is_binary = info.get('is_binary', False)
                fc_raw    = info.get('fc_raw')
                bit       = info.get('bit')

                # CORREÇÃO [4]: só rejeita se não for binário E não for coil/DI
                # E não tiver bitmask.
                # Antes: rejeitava qualquer FC3/4 sem bit, bloqueando binários
                # sem BitMask que são exatamente o caso que queremos corrigir.
                if not is_binary and fc_raw not in [1, 2] and bit is None:
                    falhas += 1
                    erros.append(
                        f"{ponto}: FC {fc_raw} sem bit não aceita valor binário"
                    )
                    continue

            ok, msg = escrever_ponto(root, net, ponto, valor_binario, unit_id=unit_id)
            if ok:
                sucesso += 1
            else:
                falhas += 1
                erros.append(f"{ponto}: {msg}")
    else:
        falhas += len(binarios)
        erros.append(f"Valor binário inválido: {valor_binario}")

    return jsonify({
        "ok":      falhas == 0,
        "sucesso": sucesso,
        "falhas":  falhas,
        "erros":   erros
    }), 200


@app.route('/ping')
def ping():
    return jsonify({"ok": True, "status": "online"}), 200


@app.route('/ip-map')
def ver_ip_map():
    return jsonify(ip_map)


@app.route('/download-log-pdf')
def download_log_pdf():
    try:
        buffer, nome = excel_logger.gerar_pdf()
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{nome}.pdf"
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/download-log-xlsx')
def download_log_xlsx():
    try:
        return send_file(
            excel_logger.file_path,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=os.path.basename(excel_logger.file_path)
        )
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/shutdown', methods=['POST'])
def shutdown():
    print("Interface fechada pelo usuário. Encerrando o simulador...")
    os._exit(0) 
    return jsonify({"status": "encerrando"}), 200

# =============================================================================
# ENTRYPOINT
# =============================================================================

def iniciar_api():
    app.run(
        host='0.0.0.0',
        port=5502,
        debug=False,
        use_reloader=False,
        threaded=True
    )

def abrir_navegador():
    webbrowser.open_new("http://127.0.0.1:5502")



if __name__ == "__main__":
    print("Servidor Modbus rodando na porta 502...")
    print("API HTTP disponível na porta 5502 para a interface gráfica.")
    threading.Thread(target=iniciar_api, daemon=True).start()
    Timer(1, abrir_navegador).start()
    try:
        StartTcpServer(context, address=("0.0.0.0", 502))
    except OSError as e:
        print(f"⚠️ Porta 502 ocupada (Docker provavelmente está rodando): {e}")
        print("🌐 Rodando apenas em modo web — escrita via TCP nos containers.")
        threading.Event().wait()
