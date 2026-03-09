<script setup lang="ts">
/**
 * OmniaOrb.vue — Expressive Neural Nexus
 *
 * A living, morphing AI consciousness visualization with emotional expression.
 * Features: organic blob morphing, neural tendrils, aurora bands, pupil-like
 * focus point, breathing rhythm, and state-driven emotional personality.
 */
import { computed } from 'vue'

const props = withDefaults(defineProps<{
    state: 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'
    audioLevel: number
    compact?: boolean
}>(), {
    compact: false
})

const emit = defineEmits<{
    click: []
}>()

/** Base size for the nexus container. */
const size = computed(() => props.compact ? 80 : 180)

/** Audio-reactive scale factor — more dramatic response. */
const audioScale = computed(() => 1 + props.audioLevel * (props.compact ? 0.08 : 0.22))

/** Tendril reach increases with audio — up to 50% longer. */
const tendrilReach = computed(() => 1 + props.audioLevel * 0.9)

/** Core brightness pulses with audio — up to 3x brighter. */
const coreBrightness = computed(() => 0.4 + props.audioLevel * 0.6)

/** Fog expansion with audio. */
const fogExpand = computed(() => 1 + props.audioLevel * 0.25)

/** Particle swarm speed multiplier (for thinking state). */
const particleSpeed = computed(() => {
    if (props.state === 'thinking') return 1 + props.audioLevel * 2
    if (props.state === 'processing') return 2.5
    return 1
})

/** Whether audio is spiking (for shockwave trigger). */
const audioSpiking = computed(() => props.audioLevel > 0.7)

const containerStyle = computed(() => ({
    width: `${size.value}px`,
    height: `${size.value}px`,
    '--audio-scale': audioScale.value,
    '--tendril-reach': tendrilReach.value,
    '--core-bright': coreBrightness.value,
    '--fog-expand': fogExpand.value,
    '--particle-speed': `${3 / particleSpeed.value}s`,
}))

function handleClick(): void {
    emit('click')
}
</script>

<template>
    <div class="nexus" :class="[`nexus--${state}`, { 'nexus--compact': compact, 'nexus--spike': audioSpiking }]"
        :style="containerStyle" role="button" tabindex="0"
        :aria-label="state === 'idle' ? 'Clicca per parlare' : `Stato: ${state}`" @click="handleClick"
        @keydown.enter="handleClick" @keydown.space.prevent="handleClick">

        <!-- Breathing wrapper — whole orb breathes organically -->
        <div class="nexus__breath">
            <!-- Ambient fog — outermost atmospheric glow -->
            <div class="nexus__fog" />

            <!-- Audio shockwave ring — appears on audio spikes -->
            <div v-if="!compact" class="nexus__shockwave" />

            <!-- Neural tendrils — synaptic connections radiating outward -->
            <div v-if="!compact" class="nexus__tendrils">
                <span v-for="i in 8" :key="i" class="nexus__tendril" />
            </div>

            <!-- Pulse ripples — expanding wave rings -->
            <div class="nexus__ripple nexus__ripple--1" />
            <div class="nexus__ripple nexus__ripple--2" />
            <div class="nexus__ripple nexus__ripple--3" />

            <!-- Aurora bands — rotating luminous bands around the orb -->
            <div v-if="!compact" class="nexus__aurora">
                <div class="nexus__aurora-band nexus__aurora-band--1" />
                <div class="nexus__aurora-band nexus__aurora-band--2" />
                <div class="nexus__aurora-band nexus__aurora-band--3" />
            </div>

            <!-- Outer membrane — iridescent morphing surface -->
            <div class="nexus__membrane">
                <div class="nexus__iridescence" />
            </div>

            <!-- Inner plasma — mid layer with depth parallax -->
            <div class="nexus__plasma" />

            <!-- Hex grid overlay — processing state crystalline geometry -->
            <div v-if="state === 'processing'" class="nexus__hexgrid" />

            <!-- Particle field — internal constellation swarm -->
            <div class="nexus__particles">
                <span v-for="i in (compact ? 6 : 16)" :key="i" class="nexus__particle" />
            </div>

            <!-- State transition flash -->
            <div class="nexus__flash" />

            <!-- Core singularity — the star at the center -->
            <div class="nexus__core">
                <div class="nexus__core-flare" />
            </div>

            <!-- Eye / Focus point — pupil-like element expressing attention -->
            <div class="nexus__eye">
                <div class="nexus__pupil" />
            </div>
        </div>
    </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════
   Expressive Neural Nexus — Living AI Consciousness
   ═══════════════════════════════════════════════════════════ */

.nexus {
    --c-gold: 201, 168, 76;
    --c-crimson: 231, 76, 60;
    --c-emerald: 46, 204, 113;
    --c-teal: 72, 201, 176;
    --c-sapphire: 100, 140, 220;

    /* State-driven colors (overridden per state) */
    --nx-hue1: var(--c-gold);
    --nx-hue2: var(--c-teal);
    --nx-glow: rgba(var(--c-gold), 0.3);
    --nx-morph-dur: 8s;
    --nx-morph-fn: ease-in-out;

    position: relative;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transform: scale(var(--audio-scale, 1));
    transition: transform 0.12s ease-out;
    isolation: isolate;
}

.nexus:focus-visible {
    outline: 2px solid rgba(var(--c-gold), 0.6);
    outline-offset: 12px;
    border-radius: 50%;
}

/* ── Breathing Wrapper — whole orb breathes ────────────── */
.nexus__breath {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
}

.nexus--idle .nexus__breath {
    animation: breathIdle 5s ease-in-out infinite;
}

.nexus--listening .nexus__breath {
    animation: breathListen 1.8s ease-in-out infinite;
}

.nexus--thinking .nexus__breath {
    animation: breathThink 3s ease-in-out infinite;
}

.nexus--speaking .nexus__breath {
    animation: breathSpeak 2.5s ease-in-out infinite;
}

.nexus--processing .nexus__breath {
    animation: breathProcess 1s linear infinite;
}

/* ── State Color Overrides ─────────────────────────────── */
.nexus--idle {
    --nx-hue1: var(--c-gold);
    --nx-hue2: var(--c-teal);
    --nx-glow: rgba(var(--c-gold), 0.2);
    --nx-morph-dur: 10s;
}

.nexus--listening {
    --nx-hue1: var(--c-crimson);
    --nx-hue2: 245, 130, 50;
    --nx-glow: rgba(var(--c-crimson), 0.35);
    --nx-morph-dur: 3s;
}

.nexus--thinking {
    --nx-hue1: var(--c-gold);
    --nx-hue2: var(--c-sapphire);
    --nx-glow: rgba(var(--c-gold), 0.3);
    --nx-morph-dur: 2s;
}

.nexus--speaking {
    --nx-hue1: var(--c-emerald);
    --nx-hue2: 100, 230, 160;
    --nx-glow: rgba(var(--c-emerald), 0.3);
    --nx-morph-dur: 4s;
}

.nexus--processing {
    --nx-hue1: var(--c-sapphire);
    --nx-hue2: var(--c-gold);
    --nx-glow: rgba(var(--c-sapphire), 0.3);
    --nx-morph-dur: 1.5s;
    --nx-morph-fn: linear;
}

/* ── Ambient Fog — audio-reactive expansion ────────────── */
.nexus__fog {
    position: absolute;
    inset: -60%;
    border-radius: 50%;
    background: radial-gradient(circle,
            var(--nx-glow) 0%,
            rgba(var(--nx-hue2), 0.08) 35%,
            transparent 65%);
    filter: blur(20px);
    opacity: 0.8;
    pointer-events: none;
    animation: fogPulse 6s ease-in-out infinite;
    transform: scale(var(--fog-expand, 1));
    transition: transform 0.15s ease-out, inset 0.5s ease;
    will-change: opacity, transform;
}

.nexus--listening .nexus__fog {
    animation: fogPulse 2s ease-in-out infinite;
    inset: -75%;
}

.nexus--speaking .nexus__fog {
    animation: fogBreath 3s ease-in-out infinite;
}

.nexus--thinking .nexus__fog {
    inset: -50%;
    animation: fogPulse 3s ease-in-out infinite;
}

/* ── Audio Shockwave — appears on loud audio spikes ───── */
.nexus__shockwave {
    position: absolute;
    inset: 5%;
    border-radius: 50%;
    border: 2px solid rgba(var(--nx-hue1), 0);
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.1s ease;
}

.nexus--spike .nexus__shockwave {
    animation: shockwaveBurst 0.6s ease-out;
}

/* ── Aurora Bands — luminous rotating energy rings ─────── */
.nexus__aurora {
    position: absolute;
    inset: 5%;
    border-radius: 50%;
    pointer-events: none;
}

.nexus__aurora-band {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    mix-blend-mode: screen;
    opacity: 0;
    transition: opacity 0.8s ease;
}

.nexus__aurora-band--1 {
    background: conic-gradient(from 0deg,
            rgba(var(--nx-hue1), 0.12) 0deg,
            transparent 60deg,
            rgba(var(--nx-hue2), 0.08) 120deg,
            transparent 180deg,
            rgba(var(--nx-hue1), 0.1) 240deg,
            transparent 300deg,
            rgba(var(--nx-hue1), 0.12) 360deg);
    animation: auroraRotate1 16s linear infinite;
}

.nexus__aurora-band--2 {
    background: conic-gradient(from 120deg,
            transparent 0deg,
            rgba(var(--nx-hue2), 0.1) 40deg,
            transparent 100deg,
            rgba(var(--nx-hue1), 0.06) 200deg,
            transparent 280deg,
            rgba(var(--nx-hue2), 0.08) 340deg,
            transparent 360deg);
    animation: auroraRotate2 22s linear infinite reverse;
}

.nexus__aurora-band--3 {
    background: conic-gradient(from 240deg,
            rgba(var(--nx-hue1), 0.06) 0deg,
            transparent 80deg,
            rgba(var(--c-sapphire), 0.05) 160deg,
            transparent 220deg,
            rgba(var(--nx-hue2), 0.07) 300deg,
            transparent 360deg);
    animation: auroraRotate1 28s linear infinite;
}

/* Aurora visible in all states except compact */
.nexus--idle .nexus__aurora-band {
    opacity: 0.5;
}

.nexus--listening .nexus__aurora-band {
    opacity: 0.9;
}

.nexus--thinking .nexus__aurora-band {
    opacity: 0.8;
}

.nexus--speaking .nexus__aurora-band {
    opacity: 0.7;
}

.nexus--processing .nexus__aurora-band {
    opacity: 1;
}

.nexus--listening .nexus__aurora-band--1 {
    animation-duration: 6s;
}

.nexus--listening .nexus__aurora-band--2 {
    animation-duration: 8s;
}

.nexus--thinking .nexus__aurora-band--1 {
    animation-duration: 8s;
}

.nexus--thinking .nexus__aurora-band--2 {
    animation-duration: 5s;
}

.nexus--processing .nexus__aurora-band--1 {
    animation-duration: 3s;
}

.nexus--processing .nexus__aurora-band--2 {
    animation-duration: 2s;
}

.nexus--processing .nexus__aurora-band--3 {
    animation-duration: 4s;
}

/* ── Neural Tendrils ───────────────────────────────────── */
.nexus__tendrils {
    position: absolute;
    inset: 0;
    pointer-events: none;
}

.nexus__tendril {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 2px;
    height: 38%;
    transform-origin: 50% 0%;
    border-radius: 1px;
    background: linear-gradient(to bottom,
            rgba(var(--nx-hue1), 0.5) 0%,
            rgba(var(--nx-hue2), 0.15) 60%,
            transparent 100%);
    opacity: 0;
    transition: opacity 0.6s ease, height 0.4s ease;
}

/* Distribute tendrils radially */
.nexus__tendril:nth-child(1) {
    transform: rotate(0deg);
}

.nexus__tendril:nth-child(2) {
    transform: rotate(45deg);
}

.nexus__tendril:nth-child(3) {
    transform: rotate(90deg);
}

.nexus__tendril:nth-child(4) {
    transform: rotate(135deg);
}

.nexus__tendril:nth-child(5) {
    transform: rotate(180deg);
}

.nexus__tendril:nth-child(6) {
    transform: rotate(225deg);
}

.nexus__tendril:nth-child(7) {
    transform: rotate(270deg);
}

.nexus__tendril:nth-child(8) {
    transform: rotate(315deg);
}

/* Idle: faint, slow pulse */
.nexus--idle .nexus__tendril {
    opacity: 0.2;
    height: 30%;
    animation: tendrilPulse 5s ease-in-out infinite;
}

.nexus--idle .nexus__tendril:nth-child(odd) {
    animation-delay: -2s;
    height: 25%;
}

/* Listening: eager reach outward */
.nexus--listening .nexus__tendril {
    opacity: 0.7;
    height: calc(42% * var(--tendril-reach));
    animation: tendrilReach 1.2s ease-in-out infinite alternate;
}

.nexus--listening .nexus__tendril:nth-child(even) {
    animation-delay: -0.4s;
    animation-duration: 0.9s;
}

/* Thinking: retracted and coiled */
.nexus--thinking .nexus__tendril {
    opacity: 0.35;
    height: 18%;
    animation: tendrilCoil 1.5s ease-in-out infinite;
}

/* Speaking: rhythmic pulse outward */
.nexus--speaking .nexus__tendril {
    opacity: 0.55;
    height: 35%;
    animation: tendrilWave 2s ease-in-out infinite;
}

.nexus--speaking .nexus__tendril:nth-child(n+5) {
    animation-delay: -1s;
}

/* Processing: geometric, rigid, fast */
.nexus--processing .nexus__tendril {
    opacity: 0.4;
    height: 28%;
    width: 1px;
    animation: tendrilScan 0.8s linear infinite;
    background: linear-gradient(to bottom,
            rgba(var(--nx-hue1), 0.6) 0%,
            rgba(var(--nx-hue1), 0) 100%);
}

/* ── Pulse Ripples ─────────────────────────────────────── */
.nexus__ripple {
    position: absolute;
    inset: 10%;
    border-radius: 50%;
    border: 1px solid rgba(var(--nx-hue1), 0.15);
    pointer-events: none;
    opacity: 0;
    animation: rippleExpand 5s ease-out infinite;
}

.nexus__ripple--2 {
    animation-delay: 1.7s;
}

.nexus__ripple--3 {
    animation-delay: 3.4s;
}

.nexus--listening .nexus__ripple {
    animation-duration: 2s;
    border-color: rgba(var(--c-crimson), 0.2);
}

.nexus--speaking .nexus__ripple {
    animation-duration: 2.5s;
    border-color: rgba(var(--c-emerald), 0.2);
}

/* ── Morphing Membrane — the living outer shape ────────── */
.nexus__membrane {
    position: absolute;
    inset: 12%;
    border-radius: 60% 40% 55% 45% / 50% 60% 40% 50%;
    background: radial-gradient(ellipse at 35% 35%,
            rgba(var(--nx-hue1), 0.25) 0%,
            rgba(var(--nx-hue2), 0.1) 45%,
            rgba(12, 14, 18, 0.85) 100%);
    box-shadow:
        0 0 30px rgba(var(--nx-hue1), 0.15),
        0 0 60px rgba(var(--nx-hue2), 0.05),
        inset 0 0 30px rgba(var(--nx-hue1), 0.1),
        inset 0 0 60px rgba(0, 0, 0, 0.5);
    overflow: hidden;
    animation: morphBlob var(--nx-morph-dur) var(--nx-morph-fn) infinite;
    will-change: border-radius, transform;
    transition: box-shadow 0.5s ease;
}

.nexus--idle .nexus__membrane {
    animation-name: morphBlobIdle;
}

.nexus--listening .nexus__membrane {
    animation-name: morphBlobListen;
    box-shadow:
        0 0 40px rgba(var(--c-crimson), 0.25),
        0 0 80px rgba(245, 130, 50, 0.08),
        inset 0 0 30px rgba(var(--c-crimson), 0.12),
        inset 0 0 60px rgba(0, 0, 0, 0.5);
}

.nexus--thinking .nexus__membrane {
    animation-name: morphBlobThink;
}

.nexus--speaking .nexus__membrane {
    animation-name: morphBlobSpeak;
    box-shadow:
        0 0 35px rgba(var(--c-emerald), 0.2),
        0 0 70px rgba(100, 230, 160, 0.07),
        inset 0 0 25px rgba(var(--c-emerald), 0.1),
        inset 0 0 60px rgba(0, 0, 0, 0.5);
}

.nexus--processing .nexus__membrane {
    animation-name: morphBlobProcess;
    border-radius: 45% 55% 50% 50% / 50% 45% 55% 50%;
}

/* ── Iridescent Surface (oil-slick effect) ─────────────── */
.nexus__iridescence {
    position: absolute;
    inset: 0;
    border-radius: inherit;
    background: conic-gradient(from 0deg at 50% 50%,
            rgba(var(--nx-hue1), 0.15) 0deg,
            rgba(var(--nx-hue2), 0.1) 60deg,
            rgba(var(--nx-hue1), 0.05) 120deg,
            rgba(var(--c-sapphire), 0.08) 180deg,
            rgba(var(--nx-hue2), 0.12) 240deg,
            rgba(var(--nx-hue1), 0.15) 360deg);
    mix-blend-mode: screen;
    animation: iridescentSpin 12s linear infinite;
    opacity: 0.7;
}

.nexus--thinking .nexus__iridescence {
    animation-duration: 4s;
    opacity: 0.9;
}

.nexus--processing .nexus__iridescence {
    animation-duration: 2s;
    opacity: 1;
}

/* ── Inner Plasma Layer ────────────────────────────────── */
.nexus__plasma {
    position: absolute;
    inset: 22%;
    border-radius: 45% 55% 50% 50% / 55% 45% 55% 45%;
    background: radial-gradient(ellipse at 40% 40%,
            rgba(var(--nx-hue1), 0.3) 0%,
            rgba(var(--nx-hue2), 0.08) 50%,
            transparent 100%);
    filter: blur(4px);
    animation: plasmaShift 6s ease-in-out infinite;
    pointer-events: none;
}

.nexus--thinking .nexus__plasma {
    animation-duration: 2s;
    filter: blur(2px);
}

.nexus--listening .nexus__plasma {
    animation-duration: 3s;
}

.nexus--processing .nexus__plasma {
    border-radius: 50%;
    animation-duration: 1.5s;
}

/* ── Hex Grid Overlay (processing state) ───────────────── */
.nexus__hexgrid {
    position: absolute;
    inset: 15%;
    border-radius: 50%;
    background:
        repeating-conic-gradient(rgba(var(--c-sapphire), 0.08) 0deg 30deg,
            transparent 30deg 60deg);
    animation: hexRotate 3s linear infinite;
    mix-blend-mode: screen;
    pointer-events: none;
    opacity: 0.6;
    mask-image: radial-gradient(circle, black 50%, transparent 80%);
    -webkit-mask-image: radial-gradient(circle, black 50%, transparent 80%);
}

/* ── Particle Field (constellation swarm inside) ───────── */
.nexus__particles {
    position: absolute;
    inset: 20%;
    pointer-events: none;
}

.nexus__particle {
    position: absolute;
    width: 3px;
    height: 3px;
    border-radius: 50%;
    background: rgba(var(--nx-hue1), 0.7);
    box-shadow: 0 0 4px rgba(var(--nx-hue1), 0.4);
    opacity: 0;
    transition: opacity 0.6s ease;
}

/* Position each particle along orbital paths */
.nexus__particle:nth-child(1) {
    top: 50%;
    left: 15%;
    animation: orbitA var(--particle-speed) linear infinite;
}

.nexus__particle:nth-child(2) {
    top: 20%;
    left: 50%;
    animation: orbitB var(--particle-speed) linear infinite;
}

.nexus__particle:nth-child(3) {
    top: 70%;
    left: 70%;
    animation: orbitA var(--particle-speed) linear infinite reverse;
}

.nexus__particle:nth-child(4) {
    top: 35%;
    left: 80%;
    animation: orbitB var(--particle-speed) linear infinite reverse;
}

.nexus__particle:nth-child(5) {
    top: 80%;
    left: 35%;
    animation: orbitC var(--particle-speed) linear infinite;
}

.nexus__particle:nth-child(6) {
    top: 15%;
    left: 65%;
    animation: orbitC var(--particle-speed) linear infinite reverse;
}

.nexus__particle:nth-child(7) {
    top: 60%;
    left: 20%;
    animation: orbitA calc(var(--particle-speed) * 1.3) linear infinite;
}

.nexus__particle:nth-child(8) {
    top: 40%;
    left: 45%;
    animation: orbitB calc(var(--particle-speed) * 0.8) linear infinite;
}

.nexus__particle:nth-child(9) {
    top: 25%;
    left: 30%;
    animation: orbitC calc(var(--particle-speed) * 1.1) linear infinite reverse;
}

.nexus__particle:nth-child(10) {
    top: 65%;
    left: 55%;
    animation: orbitA calc(var(--particle-speed) * 0.9) linear infinite;
}

.nexus__particle:nth-child(11) {
    top: 45%;
    left: 75%;
    animation: orbitB calc(var(--particle-speed) * 1.2) linear infinite reverse;
}

.nexus__particle:nth-child(12) {
    top: 55%;
    left: 40%;
    animation: orbitC calc(var(--particle-speed) * 0.7) linear infinite;
}

.nexus__particle:nth-child(13) {
    top: 35%;
    left: 65%;
    animation: orbitA calc(var(--particle-speed) * 1.3) linear infinite;
}

.nexus__particle:nth-child(14) {
    top: 70%;
    left: 35%;
    animation: orbitB calc(var(--particle-speed) * 0.85) linear infinite reverse;
}

.nexus__particle:nth-child(15) {
    top: 20%;
    left: 50%;
    animation: orbitC calc(var(--particle-speed) * 1.15) linear infinite;
}

.nexus__particle:nth-child(16) {
    top: 50%;
    left: 20%;
    animation: orbitA calc(var(--particle-speed) * 0.95) linear infinite reverse;
}

/* ── Core Singularity ──────────────────────────────────── */
.nexus__core {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 14%;
    height: 14%;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    background: radial-gradient(circle,
            rgba(255, 255, 255, calc(var(--core-bright) * 0.9)) 0%,
            rgba(var(--nx-hue1), calc(var(--core-bright) * 0.6)) 40%,
            rgba(var(--nx-hue1), 0.1) 80%,
            transparent 100%);
    box-shadow:
        0 0 8px rgba(255, 255, 255, 0.4),
        0 0 16px rgba(var(--nx-hue1), 0.4),
        0 0 32px rgba(var(--nx-hue1), 0.2),
        0 0 48px rgba(var(--nx-hue2), 0.1);
    animation: corePulse 3s ease-in-out infinite;
    z-index: 2;
}

.nexus--listening .nexus__core {
    animation: corePulse 1.5s ease-in-out infinite;
    box-shadow:
        0 0 10px rgba(255, 255, 255, 0.5),
        0 0 20px rgba(var(--c-crimson), 0.5),
        0 0 40px rgba(var(--c-crimson), 0.25),
        0 0 64px rgba(245, 130, 50, 0.1);
}

.nexus--thinking .nexus__core {
    animation: coreFlicker 1s ease-in-out infinite;
}

.nexus--speaking .nexus__core {
    animation: coreBreath 2s ease-in-out infinite;
}

.nexus--processing .nexus__core {
    animation: corePulse 0.8s linear infinite;
    border-radius: 40% 60% 50% 50%;
}

/* Core flare — lens flare streak through center */
.nexus__core-flare {
    position: absolute;
    top: 50%;
    left: -30%;
    width: 160%;
    height: 2px;
    background: linear-gradient(90deg,
            transparent 0%,
            rgba(255, 255, 255, 0.05) 25%,
            rgba(255, 255, 255, 0.3) 50%,
            rgba(255, 255, 255, 0.05) 75%,
            transparent 100%);
    border-radius: 1px;
    transform: translateY(-50%);
    animation: flareRotate 15s linear infinite;
}

.nexus--thinking .nexus__core-flare {
    animation-duration: 4s;
}

.nexus--processing .nexus__core-flare {
    animation-duration: 2s;
}

/* ── State transition flash ─────────────────────────────── */
.nexus__flash {
    position: absolute;
    inset: 10%;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(255, 255, 255, 0.2) 0%, transparent 70%);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.1s ease;
}

/* Trigger flash on any state class change via animation */
.nexus--idle .nexus__flash {
    animation: stateFlashA 0.4s ease-out;
}

.nexus--listening .nexus__flash {
    animation: stateFlashB 0.4s ease-out;
}

.nexus--thinking .nexus__flash {
    animation: stateFlashC 0.4s ease-out;
}

.nexus--speaking .nexus__flash {
    animation: stateFlashD 0.4s ease-out;
}

.nexus--processing .nexus__flash {
    animation: stateFlashE 0.4s ease-out;
}

/* ── Eye / Focus Point — pupil expressing attention ───── */
.nexus__eye {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 20%;
    height: 20%;
    transform: translate(-50%, -50%);
    border-radius: 50%;
    pointer-events: none;
    z-index: 3;
}

.nexus__pupil {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 40%;
    height: 40%;
    border-radius: 50%;
    background: radial-gradient(circle,
            rgba(255, 255, 255, 0.9) 0%,
            rgba(var(--nx-hue1), 0.7) 50%,
            rgba(var(--nx-hue1), 0.2) 100%);
    box-shadow:
        0 0 6px rgba(255, 255, 255, 0.5),
        0 0 12px rgba(var(--nx-hue1), 0.4);
    transform: translate(-50%, -50%);
    transition: width 0.4s ease, height 0.4s ease, box-shadow 0.4s ease;
}

/* Idle: pupil wanders in figure-8 (curious) */
.nexus--idle .nexus__pupil {
    width: 35%;
    height: 35%;
    animation: pupilWander 8s ease-in-out infinite;
}

/* Listening: pupil focuses upward, grows (attentive) */
.nexus--listening .nexus__pupil {
    width: 50%;
    height: 50%;
    animation: pupilFocus 2s ease-in-out infinite;
    box-shadow:
        0 0 8px rgba(255, 255, 255, 0.6),
        0 0 16px rgba(var(--c-crimson), 0.5);
}

/* Thinking: pupil contracts tight and vibrates (concentrating) */
.nexus--thinking .nexus__pupil {
    width: 20%;
    height: 20%;
    animation: pupilVibrate 0.3s ease-in-out infinite;
    box-shadow:
        0 0 4px rgba(255, 255, 255, 0.4),
        0 0 8px rgba(var(--c-gold), 0.6);
}

/* Speaking: pupil expands and pulses (projecting) */
.nexus--speaking .nexus__pupil {
    width: 55%;
    height: 55%;
    animation: pupilProject 2.5s ease-in-out infinite;
    box-shadow:
        0 0 10px rgba(255, 255, 255, 0.5),
        0 0 20px rgba(var(--c-emerald), 0.4);
}

/* Processing: pupil splits into orbital motion */
.nexus--processing .nexus__pupil {
    width: 25%;
    height: 25%;
    animation: pupilOrbit 1.2s linear infinite;
    box-shadow:
        0 0 6px rgba(var(--c-sapphire), 0.6),
        8px 0 6px rgba(var(--c-gold), 0.4);
}

/* ── Enhanced Particles — state-driven behavior ────────── */
.nexus--idle .nexus__particle {
    opacity: 0.2;
}

/* Listening: particles cluster toward top (drawn to voice) */
.nexus--listening .nexus__particle {
    opacity: 0.6;
    animation-direction: normal;
}

.nexus--listening .nexus__particle:nth-child(odd) {
    animation-name: particleClusterTop;
}

/* Thinking: particles spiral inward (concentration) */
.nexus--thinking .nexus__particle {
    opacity: 0.8;
}

.nexus--thinking .nexus__particle:nth-child(odd) {
    animation-name: particleSpiralIn;
}

/* Speaking: particles radiate outward (projection) */
.nexus--speaking .nexus__particle {
    opacity: 0.5;
}

.nexus--speaking .nexus__particle:nth-child(even) {
    animation-name: particleRadiate;
}

/* Processing: structured grid pattern */
.nexus--processing .nexus__particle {
    opacity: 0.7;
    width: 2px;
    height: 2px;
    background: rgba(var(--c-sapphire), 0.8);
    box-shadow: 0 0 6px rgba(var(--c-sapphire), 0.5), 0 0 2px rgba(var(--c-sapphire), 0.8);
}

/* ── Hover ─────────────────────────────────────────────── */
.nexus:hover .nexus__membrane {
    box-shadow:
        0 0 45px rgba(var(--nx-hue1), 0.3),
        0 0 90px rgba(var(--nx-hue2), 0.1),
        inset 0 0 30px rgba(var(--nx-hue1), 0.15),
        inset 0 0 60px rgba(0, 0, 0, 0.4);
}

.nexus:hover .nexus__core {
    box-shadow:
        0 0 12px rgba(255, 255, 255, 0.5),
        0 0 24px rgba(var(--nx-hue1), 0.5),
        0 0 48px rgba(var(--nx-hue1), 0.25),
        0 0 72px rgba(var(--nx-hue2), 0.12);
}

.nexus:active {
    transform: scale(calc(var(--audio-scale, 1) * 0.95));
}

/* ── Compact Mode ──────────────────────────────────────── */
.nexus--compact .nexus__fog {
    inset: -40%;
    filter: blur(12px);
}

.nexus--compact .nexus__membrane {
    inset: 15%;
}

.nexus--compact .nexus__plasma {
    inset: 28%;
}

.nexus--compact .nexus__core {
    width: 18%;
    height: 18%;
}

.nexus--compact .nexus__ripple {
    display: none;
}

.nexus--compact .nexus__eye {
    width: 16%;
    height: 16%;
}

.nexus--compact .nexus__particle {
    width: 2px;
    height: 2px;
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Blob Morphing
   ═══════════════════════════════════════════════════════════ */

@keyframes morphBlobIdle {
    0% {
        border-radius: 60% 40% 55% 45% / 50% 60% 40% 50%;
        transform: rotate(0deg) scale(1);
    }

    25% {
        border-radius: 45% 55% 40% 60% / 60% 45% 55% 40%;
        transform: rotate(2deg) scale(1.02);
    }

    50% {
        border-radius: 55% 45% 60% 40% / 40% 55% 45% 60%;
        transform: rotate(-1deg) scale(1);
    }

    75% {
        border-radius: 40% 60% 45% 55% / 55% 40% 60% 45%;
        transform: rotate(1deg) scale(1.01);
    }

    100% {
        border-radius: 60% 40% 55% 45% / 50% 60% 40% 50%;
        transform: rotate(0deg) scale(1);
    }
}

@keyframes morphBlobListen {
    0% {
        border-radius: 50% 50% 45% 55% / 45% 55% 50% 50%;
        transform: rotate(-2deg) scaleY(1);
    }

    20% {
        border-radius: 40% 60% 50% 50% / 55% 45% 60% 40%;
        transform: rotate(3deg) scaleY(1.06);
    }

    40% {
        border-radius: 55% 45% 40% 60% / 40% 60% 45% 55%;
        transform: rotate(-4deg) scaleX(1.08);
    }

    60% {
        border-radius: 45% 55% 60% 40% / 60% 40% 55% 45%;
        transform: rotate(2deg) scaleY(0.95);
    }

    80% {
        border-radius: 60% 40% 45% 55% / 45% 55% 40% 60%;
        transform: rotate(-3deg) scaleX(1.04);
    }

    100% {
        border-radius: 50% 50% 45% 55% / 45% 55% 50% 50%;
        transform: rotate(-2deg) scaleY(1);
    }
}

@keyframes morphBlobThink {
    0% {
        border-radius: 55% 45% 50% 50% / 50% 50% 55% 45%;
        transform: rotate(0deg) scale(0.98);
    }

    16% {
        border-radius: 48% 52% 45% 55% / 55% 45% 48% 52%;
        transform: rotate(8deg) scale(1.03);
    }

    33% {
        border-radius: 52% 48% 55% 45% / 45% 55% 52% 48%;
        transform: rotate(-5deg) scale(0.97);
    }

    50% {
        border-radius: 45% 55% 48% 52% / 52% 48% 45% 55%;
        transform: rotate(12deg) scale(1.04);
    }

    66% {
        border-radius: 55% 45% 52% 48% / 48% 52% 55% 45%;
        transform: rotate(-8deg) scale(0.99);
    }

    83% {
        border-radius: 50% 50% 45% 55% / 55% 45% 50% 50%;
        transform: rotate(5deg) scale(1.02);
    }

    100% {
        border-radius: 55% 45% 50% 50% / 50% 50% 55% 45%;
        transform: rotate(0deg) scale(0.98);
    }
}

@keyframes morphBlobSpeak {
    0% {
        border-radius: 50% 50% 50% 50% / 50% 50% 50% 50%;
        transform: scale(1);
    }

    15% {
        border-radius: 55% 45% 52% 48% / 48% 52% 45% 55%;
        transform: scale(1.05);
    }

    30% {
        border-radius: 48% 52% 50% 50% / 55% 45% 50% 50%;
        transform: scale(0.97);
    }

    50% {
        border-radius: 52% 48% 45% 55% / 50% 50% 55% 45%;
        transform: scale(1.04);
    }

    70% {
        border-radius: 45% 55% 55% 45% / 45% 55% 48% 52%;
        transform: scale(0.98);
    }

    85% {
        border-radius: 55% 45% 48% 52% / 52% 48% 55% 45%;
        transform: scale(1.03);
    }

    100% {
        border-radius: 50% 50% 50% 50% / 50% 50% 50% 50%;
        transform: scale(1);
    }
}

@keyframes morphBlobProcess {
    0% {
        border-radius: 45% 55% 50% 50% / 50% 50% 45% 55%;
        transform: rotate(0deg);
    }

    25% {
        border-radius: 48% 52% 47% 53% / 53% 47% 48% 52%;
        transform: rotate(90deg);
    }

    50% {
        border-radius: 52% 48% 53% 47% / 47% 53% 52% 48%;
        transform: rotate(180deg);
    }

    75% {
        border-radius: 47% 53% 50% 50% / 50% 50% 53% 47%;
        transform: rotate(270deg);
    }

    100% {
        border-radius: 45% 55% 50% 50% / 50% 50% 45% 55%;
        transform: rotate(360deg);
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Ambient & Glow
   ═══════════════════════════════════════════════════════════ */

@keyframes fogPulse {

    0%,
    100% {
        opacity: 0.6;
        transform: scale(1);
    }

    50% {
        opacity: 1;
        transform: scale(1.08);
    }
}

@keyframes fogBreath {

    0%,
    100% {
        opacity: 0.5;
        transform: scale(1);
    }

    30% {
        opacity: 0.9;
        transform: scale(1.06);
    }

    60% {
        opacity: 0.7;
        transform: scale(0.97);
    }
}

@keyframes rippleExpand {
    0% {
        transform: scale(1);
        opacity: 0.4;
    }

    100% {
        transform: scale(2.5);
        opacity: 0;
    }
}

@keyframes iridescentSpin {
    from {
        transform: rotate(0deg);
    }

    to {
        transform: rotate(360deg);
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Tendrils
   ═══════════════════════════════════════════════════════════ */

@keyframes tendrilPulse {

    0%,
    100% {
        opacity: 0.15;
        height: 28%;
    }

    50% {
        opacity: 0.35;
        height: 32%;
    }
}

@keyframes tendrilReach {
    0% {
        opacity: 0.5;
        height: 35%;
    }

    100% {
        opacity: 0.8;
        height: 48%;
    }
}

@keyframes tendrilCoil {

    0%,
    100% {
        opacity: 0.3;
        height: 18%;
    }

    50% {
        opacity: 0.5;
        height: 14%;
    }
}

@keyframes tendrilWave {

    0%,
    100% {
        opacity: 0.4;
        height: 30%;
    }

    25% {
        opacity: 0.65;
        height: 38%;
    }

    75% {
        opacity: 0.45;
        height: 28%;
    }
}

@keyframes tendrilScan {

    0%,
    100% {
        opacity: 0.3;
    }

    50% {
        opacity: 0.6;
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Plasma & Particles
   ═══════════════════════════════════════════════════════════ */

@keyframes plasmaShift {
    0% {
        border-radius: 45% 55% 50% 50% / 55% 45% 55% 45%;
        transform: rotate(0deg) scale(1);
    }

    33% {
        border-radius: 55% 45% 45% 55% / 45% 55% 45% 55%;
        transform: rotate(5deg) scale(1.05);
    }

    66% {
        border-radius: 50% 50% 55% 45% / 50% 50% 50% 50%;
        transform: rotate(-3deg) scale(0.97);
    }

    100% {
        border-radius: 45% 55% 50% 50% / 55% 45% 55% 45%;
        transform: rotate(0deg) scale(1);
    }
}

@keyframes orbitA {
    0% {
        transform: translate(0, 0) scale(1);
        opacity: 0.6;
    }

    25% {
        transform: translate(15px, -10px) scale(1.2);
        opacity: 0.9;
    }

    50% {
        transform: translate(5px, -20px) scale(0.8);
        opacity: 0.5;
    }

    75% {
        transform: translate(-10px, -5px) scale(1.1);
        opacity: 0.8;
    }

    100% {
        transform: translate(0, 0) scale(1);
        opacity: 0.6;
    }
}

@keyframes orbitB {
    0% {
        transform: translate(0, 0) scale(0.8);
        opacity: 0.5;
    }

    25% {
        transform: translate(-12px, 8px) scale(1.1);
        opacity: 0.85;
    }

    50% {
        transform: translate(-5px, 18px) scale(1.3);
        opacity: 0.7;
    }

    75% {
        transform: translate(8px, 6px) scale(0.9);
        opacity: 0.9;
    }

    100% {
        transform: translate(0, 0) scale(0.8);
        opacity: 0.5;
    }
}

@keyframes orbitC {
    0% {
        transform: translate(0, 0) scale(1);
        opacity: 0.7;
    }

    33% {
        transform: translate(10px, 12px) scale(1.2);
        opacity: 0.9;
    }

    66% {
        transform: translate(-8px, -8px) scale(0.7);
        opacity: 0.4;
    }

    100% {
        transform: translate(0, 0) scale(1);
        opacity: 0.7;
    }
}

@keyframes hexRotate {
    from {
        transform: rotate(0deg);
    }

    to {
        transform: rotate(60deg);
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Core Singularity
   ═══════════════════════════════════════════════════════════ */

@keyframes corePulse {

    0%,
    100% {
        transform: translate(-50%, -50%) scale(1);
        opacity: 0.85;
    }

    50% {
        transform: translate(-50%, -50%) scale(1.15);
        opacity: 1;
    }
}

@keyframes coreFlicker {

    0%,
    100% {
        transform: translate(-50%, -50%) scale(1);
        opacity: 0.8;
    }

    20% {
        transform: translate(-50%, -50%) scale(1.2);
        opacity: 1;
    }

    40% {
        transform: translate(-50%, -50%) scale(0.9);
        opacity: 0.7;
    }

    60% {
        transform: translate(-50%, -50%) scale(1.15);
        opacity: 0.95;
    }

    80% {
        transform: translate(-50%, -50%) scale(0.95);
        opacity: 0.85;
    }
}

@keyframes coreBreath {

    0%,
    100% {
        transform: translate(-50%, -50%) scale(1);
    }

    30% {
        transform: translate(-50%, -50%) scale(1.2);
    }

    60% {
        transform: translate(-50%, -50%) scale(0.9);
    }
}

@keyframes flareRotate {
    from {
        transform: translateY(-50%) rotate(0deg);
    }

    to {
        transform: translateY(-50%) rotate(360deg);
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Breathing Rhythms
   ═══════════════════════════════════════════════════════════ */

@keyframes breathIdle {

    0%,
    100% {
        transform: scale(1);
    }

    50% {
        transform: scale(1.03);
    }
}

@keyframes breathListen {

    0%,
    100% {
        transform: scale(1);
    }

    35% {
        transform: scale(1.04);
    }

    65% {
        transform: scale(0.98);
    }
}

@keyframes breathThink {
    0% {
        transform: scale(1);
    }

    40% {
        transform: scale(1.05);
    }

    60% {
        transform: scale(1.04);
    }

    100% {
        transform: scale(1);
    }
}

@keyframes breathSpeak {

    0%,
    100% {
        transform: scale(1);
    }

    15% {
        transform: scale(1.05);
    }

    30% {
        transform: scale(0.98);
    }

    50% {
        transform: scale(1.04);
    }

    70% {
        transform: scale(0.99);
    }

    85% {
        transform: scale(1.03);
    }
}

@keyframes breathProcess {

    0%,
    100% {
        transform: scale(1);
    }

    50% {
        transform: scale(1.02);
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Aurora Bands
   ═══════════════════════════════════════════════════════════ */

@keyframes auroraRotate1 {
    from {
        transform: rotate(0deg);
    }

    to {
        transform: rotate(360deg);
    }
}

@keyframes auroraRotate2 {
    from {
        transform: rotate(0deg) scale(0.95);
    }

    to {
        transform: rotate(360deg) scale(0.95);
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Audio Shockwave
   ═══════════════════════════════════════════════════════════ */

@keyframes shockwaveBurst {
    0% {
        transform: scale(1);
        border-color: rgba(var(--nx-hue1), 0.5);
        opacity: 0.8;
    }

    100% {
        transform: scale(2.2);
        border-color: rgba(var(--nx-hue1), 0);
        opacity: 0;
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — State Transition Flash
   ═══════════════════════════════════════════════════════════ */

@keyframes stateFlashA {
    0% {
        opacity: 0.5;
    }

    100% {
        opacity: 0;
    }
}

@keyframes stateFlashB {
    0% {
        opacity: 0.5;
    }

    100% {
        opacity: 0;
    }
}

@keyframes stateFlashC {
    0% {
        opacity: 0.5;
    }

    100% {
        opacity: 0;
    }
}

@keyframes stateFlashD {
    0% {
        opacity: 0.5;
    }

    100% {
        opacity: 0;
    }
}

@keyframes stateFlashE {
    0% {
        opacity: 0.5;
    }

    100% {
        opacity: 0;
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Eye / Pupil Expression
   ═══════════════════════════════════════════════════════════ */

@keyframes pupilWander {

    0%,
    100% {
        transform: translate(-50%, -50%);
    }

    12% {
        transform: translate(-40%, -60%);
    }

    25% {
        transform: translate(-35%, -50%);
    }

    37% {
        transform: translate(-45%, -40%);
    }

    50% {
        transform: translate(-55%, -45%);
    }

    62% {
        transform: translate(-60%, -55%);
    }

    75% {
        transform: translate(-50%, -60%);
    }

    87% {
        transform: translate(-45%, -48%);
    }
}

@keyframes pupilFocus {

    0%,
    100% {
        transform: translate(-50%, -60%);
    }

    50% {
        transform: translate(-50%, -55%);
    }
}

@keyframes pupilVibrate {
    0% {
        transform: translate(-50%, -50%);
    }

    25% {
        transform: translate(-48%, -51%);
    }

    50% {
        transform: translate(-52%, -49%);
    }

    75% {
        transform: translate(-49%, -52%);
    }

    100% {
        transform: translate(-50%, -50%);
    }
}

@keyframes pupilProject {

    0%,
    100% {
        transform: translate(-50%, -50%) scale(1);
    }

    25% {
        transform: translate(-50%, -50%) scale(1.15);
    }

    50% {
        transform: translate(-50%, -50%) scale(0.95);
    }

    75% {
        transform: translate(-50%, -50%) scale(1.1);
    }
}

@keyframes pupilOrbit {
    from {
        transform: translate(-50%, -50%) rotate(0deg) translateX(4px);
    }

    to {
        transform: translate(-50%, -50%) rotate(360deg) translateX(4px);
    }
}

/* ═══════════════════════════════════════════════════════════
   Keyframes — Emotion Particles
   ═══════════════════════════════════════════════════════════ */

@keyframes particleClusterTop {

    0%,
    100% {
        transform: translate(0, 0);
        opacity: 0.5;
    }

    50% {
        transform: translate(0, -15px);
        opacity: 0.9;
    }
}

@keyframes particleSpiralIn {
    0% {
        transform: translate(0, 0) scale(1);
        opacity: 0.6;
    }

    50% {
        transform: translate(-5px, -5px) scale(0.6);
        opacity: 0.9;
    }

    100% {
        transform: translate(0, 0) scale(1);
        opacity: 0.6;
    }
}

@keyframes particleRadiate {

    0%,
    100% {
        transform: translate(0, 0) scale(1);
        opacity: 0.4;
    }

    50% {
        transform: translate(8px, 8px) scale(1.3);
        opacity: 0.7;
    }
}

@media (prefers-reduced-motion: reduce) {

    .nexus__shockwave,
    .nexus__flash,
    .nexus__hexgrid {
        display: none;
    }

    .nexus__breath {
        animation: none;
    }

    .nexus__tendril {
        animation-duration: 20s !important;
    }

    .nexus__ripple {
        animation-duration: 12s !important;
    }

    .nexus__particle {
        animation-duration: 10s !important;
    }

    .nexus__aurora-band {
        animation-duration: 40s !important;
    }
}
</style>
