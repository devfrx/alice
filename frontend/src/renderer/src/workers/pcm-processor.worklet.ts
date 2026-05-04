/**
 * AudioWorklet processor that converts Float32 input to PCM-16 Int16
 * and forwards it to the main thread via MessagePort.
 *
 * Registered as "pcm-processor" in the AudioWorklet scope.
 */

declare class AudioWorkletProcessor {
  readonly port: MessagePort
  process(inputs: Float32Array[][]): boolean
}

declare function registerProcessor(
  name: string,
  processorCtor: typeof AudioWorkletProcessor,
): void

class PCMProcessor extends AudioWorkletProcessor {
  process(inputs: Float32Array[][]): boolean {
    const input = inputs[0]?.[0]
    if (!input || input.length === 0) return true

    const pcm = new Int16Array(input.length)
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]))
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
    }

    this.port.postMessage(pcm.buffer, [pcm.buffer])
    return true
  }
}

registerProcessor('pcm-processor', PCMProcessor)
