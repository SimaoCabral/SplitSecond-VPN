# Split/Second VPN — Guião de Instalação

> Rede tinc em modo switch (Layer 2) para jogar Split/Second em modo LAN pela internet.

---

## Índice

1. [Servidor (Raspberry Pi)](#1-servidor-raspberry-pi)
2. [Jogadores — Windows](#2-jogadores--windows)
3. [Jogadores — Linux](#3-jogadores--linux)
4. [Troca de chaves entre jogadores e servidor](#4-troca-de-chaves)
5. [Usar o programa GUI](#5-usar-o-programa-gui)
6. [Resolver problemas comuns](#6-resolver-problemas-comuns)

---

## 1. Servidor (Raspberry Pi)

> **Fazer apenas uma vez pelo organizador.**

### 1.1 Instalar tinc

```bash
sudo apt update && sudo apt install tinc -y
```

### 1.2 Criar estrutura de directórios

```bash
sudo mkdir -p /etc/tinc/splitsecond/hosts
```

### 1.3 Ficheiro de configuração principal

```bash
sudo nano /etc/tinc/splitsecond/tinc.conf
```

Conteúdo:

```
Name = server
Mode = switch
Port = 11655
```

### 1.4 Ficheiro de host do servidor

```bash
sudo nano /etc/tinc/splitsecond/hosts/server
```

Conteúdo (substituir pelo IP público actual):

```
Address = <IP_PUBLICO>
Port = 11655
Subnet = 10.20.0.1/32
```

> **IP dinâmico?** Se o IP público do servidor mudar frequentemente, considera usar um serviço de DNS dinâmico (ex: [DuckDNS](https://www.duckdns.org)) e colocar o hostname no campo `Address`. Os jogadores podem igualmente usar o hostname em vez do IP no programa.

### 1.5 Gerar chaves do servidor

```bash
sudo tincd -n splitsecond --generate-keys
```

Isto acrescenta automaticamente a chave pública ao ficheiro `hosts/server`.

### 1.6 Scripts de rede

```bash
sudo nano /etc/tinc/splitsecond/tinc-up
```

```bash
#!/bin/bash
ip link set $INTERFACE up
ip addr add 10.20.0.1/24 dev $INTERFACE
```

```bash
sudo nano /etc/tinc/splitsecond/tinc-down
```

```bash
#!/bin/bash
ip addr del 10.20.0.1/24 dev $INTERFACE || true
ip link set $INTERFACE down || true
```

Tornar executáveis:

```bash
sudo chmod +x /etc/tinc/splitsecond/tinc-up
sudo chmod +x /etc/tinc/splitsecond/tinc-down
```

### 1.7 Abrir portas no firewall do Pi

```bash
sudo ufw allow 11655/tcp
sudo ufw allow 11655/udp
```

### 1.8 Iniciar tinc (e activar no arranque)

```bash
sudo systemctl enable tinc@splitsecond
sudo systemctl start  tinc@splitsecond
sudo systemctl status tinc@splitsecond
```

### 1.9 Aceitar hosts de novos jogadores

Quando um jogador enviar o seu ficheiro de host, copiá-lo para o servidor:

```bash
sudo nano /etc/tinc/splitsecond/hosts/<NOME_DO_JOGADOR>
# colar o conteúdo enviado pelo jogador
```

Reiniciar o tinc para reconhecer o novo peer:

```bash
sudo systemctl restart tinc@splitsecond
```

### 1.10 Enviar o ficheiro server para os jogadores

```bash
cat /etc/tinc/splitsecond/hosts/server
```

Cada jogador precisa deste conteúdo completo (com a chave pública e `Address`).

---

## 2. Jogadores — Windows

> O programa GUI trata de tudo automaticamente — instalação, configuração e ligação.

### 2.1 Iniciar o programa

1. Copiar `splitsecond-vpn.exe` para a máquina.
2. Fazer duplo-clique — aceitar o pedido de elevação UAC.
3. O programa abre no **Passo 1** e guia todo o processo.

### 2.2 Fluxo guiado pelo programa

| Passo | O que faz |
|-------|-----------|
| **1. Instalar tinc** | Clica **"Instalar automaticamente"** — descarrega e instala tinc 1.1pre18 em modo silencioso |
| **2. Driver TAP** | Clica **"Instalar driver TAP"** — instala o adaptador de rede virtual sem linha de comandos |
| **3. Configurar jogador** | Preenche nome e IP (atribuído pelo organizador) → **"Criar ficheiros + gerar chaves"** |
| **4. Ficheiro do servidor** | Cola o `hosts/server` recebido do organizador → **"Aplicar"** · introduz o IP público do servidor → **"Aplicar IP"** |
| **5. Enviar host file** | Copia o conteúdo mostrado e envia ao organizador · assinala a confirmação |
| **6. Ligar à VPN** | Clica **"LIGAR"** · aguarda ping OK · abre o jogo |

> **⚠ Nota:** O programa detecta automaticamente o que já está feito e abre directamente no primeiro passo incompleto. Podes navegar livremente entre passos com os botões ← Anterior / Seguinte →.

### 2.3 Instalação manual (sem GUI)

<details>
<summary>Expandir instruções manuais</summary>

**Instalar tinc 1.1pre18** — descarregar de `https://www.tinc-vpn.org/packages/windows/tinc-1.1pre18-install.exe`

⚠ Não usar tinc 1.0.x — não funciona no Windows 10/11.

**Instalar driver TAP** — Linha de Comandos como Administrador:

```cmd
cd "C:\Program Files\tinc\tap-win64"
tapinstall.exe install OemWin2k.inf tap0901
```

Se o adaptador tiver outro nome, renomear:

```cmd
netsh interface set interface name="<NOME_ACTUAL>" newname="tap0901"
```

**Criar ficheiros de configuração:**

`C:\Program Files\tinc\splitsecond\tinc.conf`:
```
Name = <NOME_JOGADOR>
Mode = switch
ConnectTo = server
```

`C:\Program Files\tinc\splitsecond\hosts\<NOME_JOGADOR>`:
```
Subnet = 10.20.0.<X>/32
```

`C:\Program Files\tinc\splitsecond\hosts\server`: *(colar conteúdo enviado pelo organizador)*

**Gerar chaves** — Linha de Comandos como Administrador:
```cmd
"C:\Program Files\tinc\tinc.exe" -n splitsecond generate-rsa-keys
"C:\Program Files\tinc\tinc.exe" -n splitsecond generate-ed25519-keys
```

**Ligar:**
```cmd
"C:\Program Files\tinc\tinc.exe" -n splitsecond start
netsh interface ip set address "tap0901" static 10.20.0.<X> 255.255.255.0
```

**Regras de firewall:**
```cmd
netsh advfirewall firewall add rule name="tinc-tcp" dir=in action=allow protocol=TCP localport=11655
netsh advfirewall firewall add rule name="tinc-udp" dir=in action=allow protocol=UDP localport=11655
netsh advfirewall firewall add rule name="ICMP-Allow" protocol=icmpv4:8,any dir=in action=allow
```

**Desligar:**
```cmd
"C:\Program Files\tinc\tinc.exe" -n splitsecond stop
```

</details>

---

## 3. Jogadores — Linux

> O programa GUI trata da configuração e pode instalar o tinc automaticamente.

### 3.1 Iniciar o programa

```bash
chmod +x splitsecond-vpn
./splitsecond-vpn
```

O programa usa `pkexec` (KDE/GNOME) ou `sudo` para operações que precisam de root.

### 3.2 Fluxo guiado pelo programa

| Passo | O que faz |
|-------|-----------|
| **1. Instalar tinc** | Clica **"Instalar automaticamente"** — detecta a distro e instala com o gestor de pacotes correcto |
| **2. Configurar jogador** | Preenche nome e IP → **"Criar ficheiros + gerar chaves"** (cria `tinc.conf`, host file, scripts `tinc-up/down`) |
| **3. Ficheiro do servidor** | Cola o `hosts/server` recebido → **"Aplicar"** · introduz o IP público do servidor → **"Aplicar IP"** |
| **4. Enviar host file** | Copia o conteúdo e envia ao organizador · assinala a confirmação |
| **5. Ligar à VPN** | Clica **"LIGAR"** · aguarda ping OK · abre o jogo |

> **Bazzite:** o tinc requer `sudo rpm-ostree install tinc` seguido de reinício — o programa avisa desta limitação. Instala manualmente e volta a abrir o programa após o reinício.

### 3.3 Gestor de pacotes por distro

| Distro | Comando |
|--------|---------|
| Arch / CachyOS / Manjaro | `sudo pacman -S tinc` |
| Ubuntu / Debian | `sudo apt install tinc -y` |
| Fedora / RHEL | `sudo dnf install tinc` |
| openSUSE | `sudo zypper install tinc` |
| Bazzite | `sudo rpm-ostree install tinc` *(requer reinício)* |

### 3.4 Configuração manual (sem GUI)

<details>
<summary>Expandir instruções manuais</summary>

```bash
sudo mkdir -p /etc/tinc/splitsecond/hosts
```

`/etc/tinc/splitsecond/tinc.conf`:
```
Name = <NOME_JOGADOR>
Mode = switch
ConnectTo = server
```

`/etc/tinc/splitsecond/hosts/<NOME_JOGADOR>`:
```
Subnet = 10.20.0.<X>/32
```

`/etc/tinc/splitsecond/hosts/server`: *(colar conteúdo enviado pelo organizador)*

`/etc/tinc/splitsecond/tinc-up`:
```bash
#!/bin/bash
ip link set $INTERFACE up
ip addr add 10.20.0.<X>/24 dev $INTERFACE
```

`/etc/tinc/splitsecond/tinc-down`:
```bash
#!/bin/bash
ip addr del 10.20.0.<X>/24 dev $INTERFACE || true
ip link set $INTERFACE down || true
```

```bash
sudo chmod +x /etc/tinc/splitsecond/tinc-up
sudo chmod +x /etc/tinc/splitsecond/tinc-down
sudo tincd -n splitsecond --generate-keys
sudo tincd -n splitsecond                       # ligar
sudo pkill -f "tincd.*splitsecond"              # desligar
```

</details>

---

## 4. Troca de Chaves

Este passo é obrigatório entre **cada novo jogador** e o **servidor**, antes da primeira ligação.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        TROCA DE FICHEIROS                           │
│                                                                     │
│  JOGADOR                              SERVIDOR (ORGANIZADOR)        │
│    │                                         │                      │
│    │──── hosts/<nome_jogador> ──────────────>│                      │
│    │       (Subnet + chave pública)          │                      │
│    │                                         │                      │
│    │<─── hosts/server ─────────────────────  │                      │
│    │       (Address + Port + chave pública)  │                      │
│    │                                         │                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Ordem correcta:**

1. Jogador completa o **Passo 3** do programa (gerar chaves).
2. No **Passo 5**, copia o seu host file e envia ao organizador.
3. Organizador copia o ficheiro para `/etc/tinc/splitsecond/hosts/` e reinicia tinc.
4. Organizador envia o `hosts/server` completo ao jogador.
5. Jogador cola o conteúdo no **Passo 4** do programa e aplica.
6. Jogador assinala "Já enviei ao organizador e recebi confirmação" e avança para ligar.

**Método de troca:** colar o conteúdo numa mensagem (Discord, WhatsApp, etc.). São apenas texto com a chave pública — não há dados sensíveis.

---

## 5. Usar o Programa GUI

### Layout

O programa usa uma interface de **passos numerados** (wizard):

```
┌──────────────────────────────────────────────────────────────┐
│  SPLIT / SECOND  VPN                              ● LIGADO   │
├──────────────┬───────────────────────────────────────────────┤
│  PASSOS      │  Passo 3                                      │
│              │  Configurar jogador                           │
│  ✓ 1. tinc   │  ───────────────────────────────────────────  │
│  ✓ 2. TAP*   │  ┌─────────────────────────────────────────┐  │
│  → 3. Config │  │  Nome do jogador   [___________]        │  │
│  ○ 4. Server │  │  10.20.0. [__]                          │  │
│  ○ 5. Host   │  │  ○ tinc.conf  ○ hosts/Simao  ○ chaves   │  │
│  ○ 6. Ligar  │  │  [Criar ficheiros + gerar chaves]        │  │
│              │  └─────────────────────────────────────────┘  │
│              │                                               │
│              │  ← Anterior       3 / 6       Seguinte →      │
├──────────────┴───────────────────────────────────────────────┤
│  [00:01:23] Split/Second VPN 1.0.0 — Windows 11             │
└──────────────────────────────────────────────────────────────┘
* Passo TAP apenas no Windows
```

### Barra lateral

| Indicador | Significado |
|-----------|-------------|
| **→** laranja | Passo actual |
| **✓** verde | Passo completo (detectado automaticamente) |
| **○** cinzento | Por completar |

Clica em qualquer passo na barra lateral para navegar directamente.

### Detecção automática de estado

Ao abrir, o programa verifica cada passo e salta automaticamente para o primeiro incompleto. Podes sempre voltar atrás para editar.

| Passo | Como detecta a conclusão |
|-------|--------------------------|
| Instalar tinc | `tincd` no PATH / executável existe |
| Driver TAP *(Win)* | Adaptador `tap0901` presente |
| Configurar jogador | `tinc.conf` + host file com chave pública |
| Ficheiro do servidor | `hosts/server` com linha `Address = …` |
| Enviar host file | Checkbox "Já enviei" assinalada |
| Ligar | tincd a correr |

### Instalação automática

| Passo | Botão | O que faz |
|-------|-------|-----------|
| Instalar tinc (Linux) | **Instalar automaticamente** | Detecta a distro e corre `pkexec pacman/apt/dnf install tinc` |
| Instalar tinc (Windows) | **Instalar automaticamente** | Descarrega `tinc-1.1pre18-install.exe` e instala em modo silencioso |
| Driver TAP (Windows) | **Instalar driver TAP** | Corre `tapinstall.exe install OemWin2k.inf tap0901` (já elevado) |

### Actualização do IP do servidor

Quando o IP público do servidor mudar:

1. Pede o novo IP ao organizador.
2. No **Passo 4**, escreve o IP no campo **"IP público do servidor"** → **"Aplicar IP"**.
3. Com a checkbox **"Actualizar Address automaticamente antes de cada ligação"** activa, o programa actualiza o `hosts/server` sozinho a cada vez que clicas LIGAR.

---

## 6. Resolver Problemas Comuns

### "tinc não arrancou"

- **Windows:** verificar que o driver TAP está instalado (Passo 2) e o adaptador se chama `tap0901`.
- **Linux:** verificar que `tincd` está instalado (Passo 1) e que os scripts `tinc-up/down` são executáveis.
- Log em tempo real: `sudo journalctl -fu tinc@splitsecond`

### Ping ao servidor falha após ligar

- Confirmar que o organizador adicionou o `hosts/<nome_jogador>` e reiniciou tinc.
- Confirmar que o `hosts/server` tem o IP público correcto (`Address = ...`).
- **Windows:** confirmar com `ipconfig /all` que `10.20.0.X` aparece no adaptador `tap0901`.

### Windows: jogo não encontra outros jogadores

- Se **Radmin VPN** estiver instalado, desactivar o seu adaptador em "Ligações de Rede" antes de abrir o jogo.
- Confirmar que o IP VPN está correcto no adaptador TAP (`ipconfig /all`).

### Linux (Proton/Wine): jogo não encontra outros jogadores

O Split/Second no Linux faz bind na primeira interface disponível (geralmente ethernet).
Solução: isolar o jogo num network namespace com apenas a interface tinc + `veth` para internet.
*(Fora do âmbito do programa — ver documentação de network namespaces.)*

### IP público do servidor mudou

1. Pede o novo IP ao organizador.
2. No programa, vai ao **Passo 4** e introduz o novo IP → **"Aplicar IP"**.
3. Em alternativa, pede o `hosts/server` completo actualizado, cola-o na caixa e aplica de novo.

### "Sem privilégios para escrever"

- **Windows:** fechar e reabrir o programa — aceitar o pedido de elevação (UAC).
- **Linux:** instalar `polkit` para activar o `pkexec`. Em alternativa, correr com `sudo ./splitsecond-vpn`.

### Instalação automática falhou (Linux)

- O `pkexec` pode não estar disponível em sistemas minimalistas — instalar `polkit`.
- Se o diálogo de password não aparecer, correr o programa a partir de um terminal e instalar tinc manualmente.
- **Bazzite:** `rpm-ostree` não é suportado em modo automático — instalar manualmente e reiniciar.

---

## IPs da rede

| Host | IP VPN |
|------|--------|
| Servidor (Pi) | 10.20.0.1 |
| Jogador 1 | 10.20.0.2 |
| Jogador 2 | 10.20.0.3 |
| Jogador 3 | 10.20.0.4 |
| … | … |

Máscara: `255.255.255.0` · Porta tinc: `11655` (TCP + UDP)
