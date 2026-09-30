# Voice-Mote Specification v0.1

本文件定義 YPCloud Voice-Mote 在 AGPC 體系中的 Voice execution capability，作為產品命名、元件責任、操作介面與驗收要求的 canonical spec。Voice-Mote 不定位為另一套 PBX 產品。

本文件描述規格要求；安裝命令、CLI 與 READY 輸出均為契約或示例，不代表目前已有對應實作或通過驗收的部署。

| 欄位 | 定義 |
| --- | --- |
| Product | YPCloud Voice-Mote |
| Platform | AGPC |
| OS | Ubuntu Linux |
| Category | Agentic Voice I/O / Voice Execution |
| Installer | `voice-mote.sh` |
| APT package | `voice-mote` |
| Daemon | `voice-moted` |
| CLI | `voice-mote` |

## Canonical definition

> Voice-Mote is a Linux-native Voice Agent Execution Node on AGPC, connecting SIP/WebRTC voice to realtime AI Agents, context, tools, and actions.

核心命名關係固定為：

```text
Voice Dot                    Agent / Voice Service
    │ runs on
    ▼
Voice-Mote                   Voice Execution Node
    │ joins
    ▼
Voice-Mesh                   Distributed Voice Network
```

| 名稱 | 語意 |
| --- | --- |
| Dot | Service / Agent |
| Mote | Execution Node |
| Mesh | Network |

> Voice Dot runs on Voice-Mote. Voice-Mote runs on AGPC. Voice-Motes form Voice-Mesh.

## 1. Architecture

```text
 SIP Phone          WebRTC             PSTN
     │                 │                 │
     └─────────────────┼─────────────────┘
                       ▼
                  Voice-Mote
          ┌────────────────────────┐
          │ OpenSIPS               │
          │ SIP Signaling          │
          └────────────┬───────────┘
                       ▼
          ┌────────────────────────┐
          │ RTPengine              │
          │ RTP / SRTP Media       │
          └────────────┬───────────┘
                       ▼
          ┌────────────────────────┐
          │ voice-moted            │
          │ Session / Voice Dot    │
          │ Realtime AI / Context  │
          │ Policy                 │
          └────────────┬───────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       GPT Live      uChat         MCP
          └────────────┼────────────┘
                       ▼
                 Agent / Action
```

此圖表達邏輯責任與整合關係；實際 signaling、media 與模型音訊介面的連接方式由實作設計補充。

OpenSIPS 管 signaling；RTPengine 管 media；Voice-Mote 管 Agent voice execution。Voice-Mote 不重新實作 SIP server 或 media engine。

## 2. Components

| Component | Responsibility |
| --- | --- |
| `voice-moted` | Voice-Mote control/runtime daemon |
| `voice-mote` | CLI |
| OpenSIPS | SIP registrar、routing、authentication、trunk |
| RTPengine | RTP/SRTP、NAT traversal、media proxy |
| Voice Dot Runtime | Voice Agent execution |
| GPT Live adapter | Realtime model connection |
| `uchatd` | User/Agent/Mesh communication |
| `mote-mcpd` | MCP Tool I/O |
| `contextd` | Voice/session/user context |
| S | Identity、policy、authorization、audit |
| O | Provisioning、operations、billing |

`voice-moted` 是 YPCloud 自有的核心控制與執行元件。

## 3. Installation

前置順序：

```text
Ubuntu → agpc.sh → AGPC Ready → voice-mote.sh → Voice-Mote Ready
```

正式發布的標準 UX：

```sh
sudo ./agpc.sh
sudo ./voice-mote.sh
voice-mote status
```

進階 lifecycle 介面：

```sh
voice-mote install
voice-mote upgrade
voice-mote repair
voice-mote verify
voice-mote doctor
voice-mote uninstall
```

`voice-mote.sh` 只負責 bootstrap；正式 package/version lifecycle 由 apt repository 管理。

### 套件與 bootstrap 契約

APT 套件名稱固定為 `voice-mote`。`voice-mote.sh` 是安裝入口，`voice-mote` 是操作 CLI，`voice-moted` 是 control/runtime daemon；三者的角色分開定義。

Bootstrap 流程：

1. 確認 Ubuntu Linux、運作中的 systemd 與 AGPC Ready。
2. 檢查既有套件狀態及 APT 相依關係。
3. 從已配置且受信任的 APT repository 更新索引，預覽並安裝 `voice-mote`，拒絕需要移除套件的交易。
4. 由正式套件管理相依元件、設定及服務 lifecycle；沿用 AGPC identity。
5. 執行 `voice-mote verify`，確認 Voice-Mote capability。

套件安裝完成與 capability 驗證通過是不同狀態。若安裝後驗證失敗，bootstrap 必須回傳失敗，保留已安裝套件供設定與診斷，不宣告 Voice-Mote Ready。

### 目前 bootstrap 整合狀態

Bootstrap 版本為 `0.1.0-bootstrap.1`，發布目標為 [voice-mote.sh](https://motebus.github.io/download/voice-mote.sh)，附有 script 與 source record 的 archive 簽章。發布來源為 `motebus/download`；詳細操作見 [安裝說明](VOICE-MOTE-INSTALL.md)。

腳本沿用主機既有受信任 APT sources，不新增 repository 或信任金鑰，也不自動執行 `agpc.sh`。此次發布只包含 bootstrap，不包含 `voice-moted` 或 Voice runtime 套件。發布準備時，已驗證的正式 APT 索引尚未包含 `voice-mote`。

預設以 `/usr/bin/agpc-manager ready --json` 檢查 AGPC，要求 `state=ready`、`live_verified=true`，且 scope 不得為 `local-precheck`。目前已知的 local-precheck 契約不足以通過此 gate。已有正式 live acceptance checker 時，可用 `--agpc-verify` 指定其絕對路徑；checker 接受零個參數，只有完整 AGPC Ready 時才能回傳 exit code 0。程式及父目錄必須由 root 擁有、不可由其他使用者寫入且不可為 symlink。

```sh
bash ./voice-mote.sh --help
bash ./voice-mote.sh --version
sudo bash ./voice-mote.sh --check
sudo bash ./voice-mote.sh --agpc-verify /absolute/path/to/agpc-ready-check
```

`--check` 使用 cached APT indexes 檢查 prerequisites 與模擬交易，不安裝套件。`--yes` 接受 APT 安裝交易，可用於已授權的非互動安裝。APT source 必須事先完成受信任的簽章與 keyring 配置，不得透過 `trusted=yes` 等設定略過驗證。

標準零參數入口會執行前置檢查；AGPC Ready 或正式套件缺失時必須停止，不得以 local precheck、安裝完成或服務 running 代替 Voice-Mote Ready。完整 runtime 安裝與 live capability 驗收仍需後續套件發布及部署證據。

## 4. Node identity

Voice-Mote 繼承 AGPC identity，不建立第二個 machine identity。

```yaml
node:
  name: agpc-office
  mote: agpc-office.mote
voice:
  enabled: true
  role: voice-mote
```

```text
agpc-office.mote
    ├── Agent Execution
    ├── Agentic I/O
    └── Voice-Mote capability
```

Voice-Mote 是 Mote capability，不是另一台虛擬機或另一種 node identity。

## 5. Voice Dot

Voice Dot 是部署到 Voice-Mote 上的 Agent Service。

```yaml
apiVersion: voice.ypcloud/v1
kind: VoiceDot
metadata:
  name: sales
spec:
  endpoint:
    sip: sales@voice.example.com
  agent:
    name: sales-agent
  model:
    provider: openai
    mode: realtime
  context:
    provider: contextd
  tools:
    - crm
    - calendar
  communication:
    uchat: true
  security:
    policy: sales-voice
```

Voice Dot 管理介面：

```sh
voice-mote dot list
voice-mote dot add sales
voice-mote dot show sales
voice-mote dot enable sales
voice-mote dot disable sales
voice-mote dot remove sales
```

## 6. Call lifecycle

```text
Incoming SIP INVITE
    → S Identity / Policy
    → OpenSIPS Route
    → Create Voice Session
    → RTPengine Media
    → Resolve Voice Dot
    → Connect GPT Live
    → Conversation
    → Intent
    → Agent
    → MCP / Tool / RUN
    → Result
    → Voice Response
    → BYE
    → Audit + Session Close
```

Voice 進入既有 AGPC execution loop：

```text
Voice → Intent → Agent → Agentic I/O → Execution → Verification → Voice Response
```

## 7. Events

Voice event 使用既有 uChat event model，不另建 message bus。

```text
voice.call.incoming
voice.call.ringing
voice.call.answered
voice.call.connected
voice.media.started
voice.media.stopped
voice.transcript.partial
voice.transcript.final
voice.intent.detected
voice.agent.started
voice.agent.action
voice.tool.call
voice.tool.result
voice.call.transferred
voice.call.ended
voice.call.failed
```

事件示例：

```json
{
  "type": "voice.call.incoming",
  "mote": "agpc-office.mote",
  "dot": "sales",
  "call_id": "call-1234"
}
```

Voice-Mote 整合既有 uChat 語意：

```text
uChat
├── chat
├── ask
├── task
├── event
├── result
├── approval
└── command
```

## 8. CLI contract

第一版核心操作介面：

```sh
voice-mote status
voice-mote doctor
voice-mote verify
voice-mote dot list
voice-mote dot show <dot>
voice-mote call list
voice-mote call show <id>
voice-mote call hangup <id>
voice-mote sip status
voice-mote media status
voice-mote mesh status
voice-mote logs
```

| Command | Operational semantics |
| --- | --- |
| `status` | 現在是否 running |
| `doctor` | 哪裡有問題 |
| `verify` | 是否真正具備 Voice-Mote capability |

Lifecycle 與 Voice Dot 管理命令分別見第 3、5 節。

## 9. Ready specification

Voice-Mote Ready 必須涵蓋以下驗收項目。清單表示要求，勾選必須由部署驗證結果支持。

- [ ] AGPC
- [ ] Linux / systemd
- [ ] Voice Identity（繼承 AGPC identity）
- [ ] SIP
- [ ] SIP TLS
- [ ] RTP
- [ ] SRTP
- [ ] Voice Dot
- [ ] Realtime AI
- [ ] uChat
- [ ] MCP
- [ ] S Policy
- [ ] Audit

`voice-mote verify` 全部通過時的目標輸出：

```text
YPCloud Voice-Mote
AGPC          READY
SIP           READY
MEDIA         READY
AI            READY
VOICE DOTS    READY
UCHAT         READY
MCP           READY
SECURITY      READY
VOICE-MOTE READY
```

程序 running 本身不足以宣告 Voice-Mote Ready；`verify` 必須確認上述 capability。

## 10. Voice-Mesh

先完成單台 Voice-Mote 獨立運作，再加入 Voice-Mesh。

```text
                       Voice-Mesh
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Voice-Mote A Voice-Mote B Voice-Mote C
          office.mote  sales.mote  service.mote
              │            │            │
          Voice Dots   Voice Dots   Voice Dots
```

Mesh 層首先負責：

- Discovery
- Routing
- Presence
- Voice Dot location
- Task handoff
- Call handoff
- Agent handoff
- uChat coordination
- Policy

Voice-Mesh 不等同 SIP cluster；RTP media mixing 不是此層的首要責任。

## 11. 與 AGPC 架構的關係

```text
                       AGPC
                         │
                  Agent Execution
                         │
                    Agentic I/O
              ┌──────────┼──────────┐
              ▼          ▼          ▼
             RUN        MCP       Voice
              │          │          │
              │          │      Voice-Mote
              └──────────┼──────────┘
                         ▼
                     Execution
```

在 DBSCOM 架構中，Voice-Mote 是 Agentic I/O capability，不新增 V Channel。控制、工具、訊息、安全與營運沿用既有 D/M/S/O 等語意。

Canonical statement：

> Voice Dot runs on Voice-Mote. Voice-Mote runs on AGPC. Voice-Motes form Voice-Mesh.
