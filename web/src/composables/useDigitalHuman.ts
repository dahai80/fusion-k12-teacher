import { computed, onUnmounted, reactive, ref, shallowRef } from 'vue'
import { Room, RoomEvent, Track } from 'livekit-client'
import { digitalHumanApi, digitalHumanWsUrl } from '@/api/endpoints'

export interface DhPage {
    index: number
    title: string
    text: string
    emotion: string
    phase: string
    question: any
    checkpoint: any
}

export interface DhSession {
    session_id: string
    page_count: number
    pages: DhPage[]
    tts_available: boolean
    asr_available: boolean
    avatar_available: boolean
    livekit_available?: boolean
    livekit_url?: string
    token?: string
    room?: string
}

export type AgentState = 'idle' | 'ai_thinking' | 'ai_speaking' | 'user_speaking' | 'error'

const LIVEKIT_SUPPORTED = typeof Room !== 'undefined'

export function useDigitalHuman() {
    const session = ref<DhSession | null>(null)
    const agentState = ref<AgentState>('idle')
    const currentPageIdx = ref(0)
    const lastNarrate = ref<any>(null)
    const lastQa = ref<any>(null)
    const errorMsg = ref('')
    const connected = ref(false)
    const busy = ref(false)
    const recording = ref(false)
    const livekitConnected = ref(false)
    const videoTrackAttached = ref(false)
    let ws: WebSocket | null = null
    const room = shallowRef<Room | null>(null)
    let mediaRecorder: MediaRecorder | null = null
    let audioCtx: AudioContext | null = null
    let micStream: MediaStream | null = null
    let pendingBinaryIsAudio = true

    function stateFromEvent(event: string): AgentState {
        if (event === 'narrate_start' || event === 'asr_start' || event === 'asr_ack') return 'ai_thinking'
        if (event === 'narrate_done' || event === 'qa_done') return 'ai_speaking'
        if (event === 'error') return 'error'
        return 'idle'
    }

    async function playAudio(blob: Blob) {
        try {
            const arr = new Uint8Array(await blob.arrayBuffer())
            const ab = arr.buffer.slice(arr.byteOffset, arr.byteOffset + arr.byteLength)
            if (!audioCtx) audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)()
            const dec = await audioCtx.decodeAudioData(ab)
            const src = audioCtx.createBufferSource()
            src.buffer = dec
            src.connect(audioCtx.destination)
            src.start()
            src.onended = () => { if (agentState.value === 'ai_speaking') agentState.value = 'idle' }
        } catch (e) {
            console.warn('dh: audio decode failed', e)
        }
    }

    async function connectLiveKit(token: string, roomName: string, videoEl: HTMLVideoElement | null) {
        if (!LIVEKIT_SUPPORTED || !token) return
        try {
            const r = new Room({ adaptiveStream: true, dynacast: true })
            r.on(RoomEvent.TrackSubscribed, (track) => {
                if (track.kind === Track.Kind.Video && videoEl) {
                    track.attach(videoEl)
                    videoTrackAttached.value = true
                }
                if (track.kind === Track.Kind.Audio) {
                    const el = track.attach() as HTMLAudioElement
                    el.autoplay = true
                    document.body.appendChild(el)
                }
            })
            r.on(RoomEvent.Disconnected, () => { livekitConnected.value = false })
            const url = session.value?.livekit_url || `ws://${location.hostname}:7880`
            await r.connect(url, token)
            room.value = r
            livekitConnected.value = true
        } catch (e) {
            console.warn('dh: livekit connect failed, degrade to WS-only', e)
            livekitConnected.value = false
        }
    }

    async function createSession(body: any, videoEl: HTMLVideoElement | null = null): Promise<DhSession | null> {
        errorMsg.value = ''
        try {
            const res = await digitalHumanApi.createSession(body) as DhSession
            session.value = res
            currentPageIdx.value = 0
            try {
                const tok = await digitalHumanApi.token({ session_id: res.session_id }) as any
                res.livekit_available = !!tok.livekit_available
                res.livekit_url = tok.livekit_url
                res.token = tok.token
                res.room = tok.room
                session.value = { ...res }
                if (tok.livekit_available && tok.token) {
                    await connectLiveKit(tok.token, tok.room, videoEl)
                }
            } catch { /* token optional */ }
            connectWs(res.session_id)
            return res
        } catch (e: any) {
            errorMsg.value = e?.message || String(e)
            return null
        }
    }

    function connectWs(sid: string) {
        if (ws) { try { ws.close() } catch {} }
        ws = new WebSocket(digitalHumanWsUrl(sid))
        ws.binaryType = 'arraybuffer'
        ws.onopen = () => { connected.value = true }
        ws.onclose = () => { connected.value = false }
        ws.onerror = () => { connected.value = false; errorMsg.value = 'WS 连接失败' }
        ws.onmessage = async (ev) => {
            if (typeof ev.data === 'string') {
                try {
                    const msg = JSON.parse(ev.data)
                    if (msg.event) agentState.value = stateFromEvent(msg.event)
                    if (msg.event === 'ready') {
                        if (msg.data?.asr_available !== undefined && session.value) {
                            session.value.asr_available = msg.data.asr_available
                        }
                    } else if (msg.event === 'narrate_done') {
                        lastNarrate.value = msg.data
                        busy.value = false
                        pendingBinaryIsAudio = msg.data?.has_audio
                    } else if (msg.event === 'qa_done') {
                        lastQa.value = msg.data
                        busy.value = false
                        pendingBinaryIsAudio = msg.data?.has_audio
                    } else if (msg.event === 'asr_start') {
                        agentState.value = 'user_speaking'
                    } else if (msg.event === 'finished') {
                        agentState.value = 'idle'
                        busy.value = false
                    } else if (msg.event === 'error') {
                        errorMsg.value = msg.data?.message || '未知错误'
                        busy.value = false
                    }
                } catch {}
            } else if (ev.data instanceof ArrayBuffer) {
                if (pendingBinaryIsAudio) {
                    await playAudio(new Blob([ev.data], { type: 'audio/wav' }))
                    pendingBinaryIsAudio = false
                }
            }
        }
    }

    function sendWs(action: string, extra: Record<string, any> = {}) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action, ...extra }))
            return true
        }
        return false
    }

    async function narrate(idx: number) {
        if (!session.value) return
        currentPageIdx.value = idx
        busy.value = true
        agentState.value = 'ai_thinking'
        pendingBinaryIsAudio = false
        if (!sendWs('narrate_page', { idx })) {
            try { lastNarrate.value = await digitalHumanApi.narrate({ session_id: session.value.session_id, idx }) }
            catch (e: any) { errorMsg.value = e?.message || String(e) }
            finally { busy.value = false; agentState.value = 'idle' }
        }
    }

    async function raiseHand(text: string) {
        if (!session.value || !text.trim()) return
        busy.value = true
        agentState.value = 'ai_thinking'
        pendingBinaryIsAudio = false
        if (!sendWs('raise_hand', { text })) {
            try { lastQa.value = await digitalHumanApi.raiseHand({ session_id: session.value.session_id, text }) }
            catch (e: any) { errorMsg.value = e?.message || String(e) }
            finally { busy.value = false; agentState.value = 'idle' }
        }
    }

    async function startRecording() {
        if (!session.value || recording.value) return
        try {
            micStream = await navigator.mediaDevices.getUserMedia({ audio: true })
            const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg'
            mediaRecorder = new MediaRecorder(micStream, { mimeType: mime })
            const chunks: BlobPart[] = []
            mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data) }
            mediaRecorder.onstop = async () => {
                const blob = new Blob(chunks, { type: mime })
                if (ws && ws.readyState === WebSocket.OPEN) {
                    const buf = await blob.arrayBuffer()
                    ws.send(buf)
                    busy.value = true
                    agentState.value = 'user_speaking'
                }
                chunks.length = 0
            }
            mediaRecorder.start()
            recording.value = true
        } catch (e: any) {
            errorMsg.value = '麦克风不可用: ' + (e?.message || String(e))
            recording.value = false
        }
    }

    function stopRecording() {
        if (mediaRecorder && recording.value) {
            mediaRecorder.stop()
            recording.value = false
        }
        if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null }
    }

    async function finish() {
        if (!session.value) return
        stopRecording()
        busy.value = true
        sendWs('finish')
        try { await digitalHumanApi.finish({ session_id: session.value.session_id }) }
        catch {}
        busy.value = false
        agentState.value = 'idle'
    }

    function close() {
        if (ws) { try { ws.close() } catch {} ws = null }
        connected.value = false
        stopRecording()
        if (room.value) { try { room.value.disconnect() } catch {} room.value = null }
        livekitConnected.value = false
        if (audioCtx) { try { audioCtx.close() } catch {} audioCtx = null }
    }

    onUnmounted(close)

    const currentPage = computed<DhPage | null>(() => {
        if (!session.value) return null
        return session.value.pages[currentPageIdx.value] || null
    })

    return reactive({
        session, agentState, currentPageIdx, currentPage,
        lastNarrate, lastQa, errorMsg, connected, busy,
        recording, livekitConnected, videoTrackAttached,
        createSession, narrate, raiseHand, startRecording, stopRecording, finish, close,
    })
}
