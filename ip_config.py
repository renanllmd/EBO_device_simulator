import sys
import yaml
import subprocess
import os
import tempfile
import time
from flask import jsonify

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IP_FIXO_FALLBACK = "192.168.250.250"
MASCARA_FIXO     = "255.255.255.0"


def obter_ips_do_compose():
    ips = set()
    compose_path = os.path.join(BASE_DIR, 'docker-compose.yml')

    if not os.path.exists(compose_path):
        print(f"[IP-ETH] ⚠️ docker-compose.yml não encontrado em: {compose_path}")
        return []

    with open(compose_path, 'r', encoding='utf-8') as f:
        compose = yaml.safe_load(f)

    for svc in compose.get('services', {}).values():
        for port in svc.get('ports', []):
            partes = str(port).split(':')
            if len(partes) == 3:
                ip = partes[0]
                if len(ip.split('.')) == 4:
                    ips.add(ip)

    return list(ips)


def ethernet_esta_em_dhcp(nome_interface="Ethernet") -> bool:
    try:
        resultado = subprocess.run(
            f'netsh interface ipv4 show config name="{nome_interface}"',
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        saida = resultado.stdout.lower()
        return "dhcp" in saida and any(tok in saida for tok in ("yes", "sim", "enabled", "habilitado"))
    except Exception as e:
        print(f"[IP-ETH] ⚠️ Não foi possível verificar DHCP: {e}")
        return False


def executar_netsh_admin(comandos):
    if not comandos:
        return

    log_path = None

    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.ps1', delete=False, encoding='utf-8'
    ) as f:
        script_path = f.name
        log_path = script_path.replace('.ps1', '.log')
        f.write(f"& {{\r\n{chr(13).join(comandos)}\r\n}} *>&1 | Out-File -FilePath '{log_path}' -Encoding utf8\r\n")

    cmd = [
        'powershell',
        '-WindowStyle', 'Hidden',
        '-Command',
        f"Start-Process powershell -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"{script_path}\"' -Verb RunAs -Wait"
    ]

    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    resultado = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        creationflags=creation_flags,
    )

    time.sleep(1.5)

    if log_path:
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as lf:
                log_content = lf.read().strip()
            if log_content:
                print(f"[IP-ETH] 📋 Output netsh:\n{log_content}")
            os.unlink(log_path)
        except Exception:
            pass

    try:
        os.unlink(script_path)
    except OSError:
        pass

    if resultado.returncode == 0:
        print("[IP-ETH] ✅ Comandos enviados.")
    else:
        saida = (resultado.stdout + resultado.stderr).strip()
        print(f"[IP-ETH] ⚠️ Falha no launcher: {saida}")


def _derivar_ip_fallback(ips: list) -> str:
    try:
        partes = ips[0].split('.')
        if len(partes) == 4:
            return f"{partes[0]}.{partes[1]}.{partes[2]}.250"
    except Exception:
        pass
    return IP_FIXO_FALLBACK


def remover_ips_ethernet(ips) -> list:
    """Monta e retorna comandos de remoção. Não executa."""
    comandos = []
    for ip in ips:
        comandos.append(
            f'netsh interface ipv4 delete address name=Ethernet address={ip}'
        )
        print(f"[IP-ETH] 🗑️ Agendada remoção do IP {ip}")
    return comandos


def adicionar_ips_ethernet(ips, mascara="255.255.255.0") -> list:
    """Monta e retorna comandos de adição. Não executa."""
    if not ips:
        print("[IP-ETH] Nenhum IP do Compose para adicionar.")
        return []

    comandos = []

    if ethernet_esta_em_dhcp():


        ip_fallback = _derivar_ip_fallback(ips)

        partes = ip_fallback.split('.')
        ultimo = int(partes[3])
        while ip_fallback in ips:
            ultimo = (ultimo % 254) + 1  # cicla entre 1-254, nunca .0 ou .255
            ip_fallback = f"{partes[0]}.{partes[1]}.{partes[2]}.{ultimo}"

        print(f"[IP-ETH] ⚠️ Ethernet em DHCP — convertendo para estático com {ip_fallback}")
        comandos.append(
            f'netsh interface ipv4 set address "Ethernet" static {ip_fallback} {MASCARA_FIXO} none'
        )
    else:
        print("[IP-ETH] ✅ Ethernet com IP estático — fallback não necessário.")

    for ip in ips:
        comandos.append(
            f'netsh interface ipv4 add address name=Ethernet address={ip} mask={mascara} skipassource=true'
        )
        print(f"[IP-ETH] ➕ Agendado IP {ip}")

    return comandos


_ips_adicionados_anteriormente = []


def sincronizar_ips_ethernet():
    global _ips_adicionados_anteriormente

    fila  = remover_ips_ethernet(_ips_adicionados_anteriormente)
    novos = obter_ips_do_compose()
    fila += adicionar_ips_ethernet(novos)

    executar_netsh_admin(fila)  # única elevação UAC
    _ips_adicionados_anteriormente = novos


def sync_ips():
    try:
        ips = obter_ips_do_compose()
        sincronizar_ips_ethernet()
        return jsonify({
            "ok": True,
            "ips_sincronizados": ips
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500