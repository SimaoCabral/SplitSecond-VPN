# Split/Second VPN — Contexto para Claude Code

## Objetivo
Criar um programa GUI (Python + CustomTkinter) cross-platform (Windows + Linux) que permite a jogadores ligarem-se facilmente a uma rede tinc VPN para jogar Split/Second em modo LAN pela internet. O programa deve cobrir: configuração inicial, ligar, desligar, e resolver automaticamente mudanças de IP público do servidor.

## Arquitetura da rede

### Servidor (já configurado)
- Raspberry Pi 5 com Raspberry Pi OS Lite (64-bit)
- Tinc em modo switch (Layer 2) — necessário para broadcasts UDP
- Porta: 11655 (TCP+UDP), port forwarding já configurado no router
- Rede VPN: 10.20.0.0/24, servidor em 10.20.0.1
- Nome da rede tinc: `splitsecond`
- Nome do host: `server`
- Ficheiros em `/etc/tinc/splitsecond/`

### Jogadores (o programa é para eles)
- Windows (maioria) e Linux
- Ligam-se ao Pi via tinc
- IPs atribuídos: 10.20.0.2, 10.20.0.3, etc.

## Porque tinc e não ZeroTier
O ZeroTier opera em Layer 3 e NÃO encaminha broadcasts UDP 255.255.255.255 entre peers. O Split/Second usa broadcasts UDP na porta 9100 para descoberta LAN. O tinc em modo switch opera em Layer 2, encaminha broadcasts como uma LAN real. Isto foi confirmado após horas de testes.

## Problema do IP público dinâmico
O IP público do organizador pode mudar. O ficheiro `hosts/server` contém o IP público do servidor e precisa de estar atualizado em todos os jogadores. Soluções possíveis:
- Dynamic DNS (ex: noip, duckdns) — o servidor regista um hostname fixo
- O programa pode verificar/atualizar o IP automaticamente via um endpoint simples (ex: ficheiro num servidor web, ou API)
- O Pi pode correr um script que publica o IP atual para um serviço acessível

A solução ideal: o Pi publica o seu IP público num serviço gratuito (ex: DuckDNS) e o programa dos jogadores usa o hostname em vez do IP no ficheiro `hosts/server`. Assim nunca precisam de atualizar manualmente.

## Configuração tinc — jogador Windows

### Pré-requisitos
1. Tinc 1.1pre18: https://www.tinc-vpn.org/packages/windows/tinc-1.1pre18-install.exe
2. Driver TAP: `cd "C:\Program Files\tinc\tap-win64"` → `tapinstall.exe install OemWin2k.inf tap0901`

### Ficheiros em C:\Program Files\tinc\splitsecond\

**tinc.conf:**
```
Name = NOME_JOGADOR
Mode = switch
ConnectTo = server
```

**hosts/NOME_JOGADOR:**
```
Subnet = 10.20.0.X/32
<CHAVE_PUBLICA>
```

**hosts/server:** (copiado do organizador, contém IP público + chave)

### Comandos Windows
```cmd
# Gerar chaves
"C:\Program Files\tinc\tinc.exe" -n splitsecond generate-rsa-keys
"C:\Program Files\tinc\tinc.exe" -n splitsecond generate-ed25519-keys

# Iniciar
"C:\Program Files\tinc\tinc.exe" -n splitsecond start

# Configurar IP no adaptador TAP
netsh interface ip set address "tap0901" static 10.20.0.X 255.255.255.0

# Parar
"C:\Program Files\tinc\tinc.exe" -n splitsecond stop

# Firewall
netsh advfirewall firewall add rule name="tinc-tcp" dir=in action=allow protocol=TCP localport=11655
netsh advfirewall firewall add rule name="tinc-udp" dir=in action=allow protocol=UDP localport=11655
netsh advfirewall firewall add rule name="ICMP-Allow" protocol=icmpv4:8,any dir=in action=allow
```

## Configuração tinc — jogador Linux

### Instalação
- Arch/CachyOS: `sudo pacman -S tinc`
- Debian/Ubuntu: `sudo apt install tinc -y`
- Bazzite: `sudo rpm-ostree install tinc` (requer reinício)

### Ficheiros em /etc/tinc/splitsecond/
Mesma estrutura que Windows. Scripts tinc-up e tinc-down:

**tinc-up:**
```bash
#!/bin/bash
ip link set $INTERFACE up
ip addr add 10.20.0.X/24 dev $INTERFACE
```

**tinc-down:**
```bash
#!/bin/bash
ip addr del 10.20.0.X/24 dev $INTERFACE
ip link set $INTERFACE down
```

### Comandos Linux
```bash
sudo tincd -n splitsecond --generate-keys  # gerar chaves
sudo tincd -n splitsecond                  # iniciar
sudo pkill tincd                           # parar
```

## Problemas conhecidos e soluções

### Windows: adaptador TAP não encontrado pelo tinc
- tinc 1.0.36 NÃO funciona no Windows moderno — usar 1.1pre18
- O driver TAP precisa de ser instalado manualmente via tapinstall.exe
- O adaptador pode precisar de ser renomeado para "tap0901" via `netsh interface set interface`

### Windows: jogo usa interface errada
- Se Radmin VPN estiver instalado, o jogo pode preferir essa interface
- Solução: desativar o adaptador Radmin VPN nas ligações de rede

### Linux: jogo usa interface ethernet em vez de tinc
- O Split/Second no Linux (Wine/Proton) faz bind à primeira interface disponível (ethernet)
- Solução testada: network namespace que isola o jogo com apenas a interface tinc + veth para internet
- Esta é uma questão separada do programa — o programa apenas gere a ligação VPN

## Requisitos do programa GUI

### Funcionalidades
1. **Setup inicial**: pedir nome e IP, criar ficheiros de configuração, gerar chaves, configurar firewall (Windows)
2. **Receber ficheiro do servidor**: campo para colar o conteúdo do hosts/server ou obtê-lo automaticamente via DuckDNS/URL
3. **Ligar**: iniciar tinc, configurar IP no adaptador, testar ping ao servidor
4. **Desligar**: parar tinc
5. **Estado**: mostrar se está ligado ou desligado, com feedback visual
6. **Copiar host file**: para o jogador enviar ao organizador
7. **Auto-elevação**: no Windows pedir permissões de administrador automaticamente
8. **Guardar configuração**: lembrar nome e IP entre sessões

### Tecnologia
- Python 3 + CustomTkinter para GUI moderna
- Compilar com PyInstaller como executável standalone (.exe no Windows, binário no Linux)
- Cross-platform: funcionar em Windows e Linux sem alterações
- Design dark theme, estilo gaming/racing inspirado no Split/Second

### Estrutura de ficheiros esperada
```
splitsecond-vpn/
├── splitsecond_vpn.py      # programa principal
├── build.bat               # compilar no Windows
├── build.sh                # compilar no Linux
└── requirements.txt        # dependências
```

## Tarefas para o Claude Code
1. Criar o programa GUI completo (splitsecond_vpn.py)
2. Implementar resolução automática do IP público (DuckDNS ou alternativa)
3. Criar scripts de build para Windows e Linux
4. Testar e compilar como executável standalone
5. Verificar que todos os comandos tinc estão corretos para ambas as plataformas
