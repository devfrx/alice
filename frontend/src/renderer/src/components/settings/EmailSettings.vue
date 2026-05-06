<template>
    <div class="sv__section-head">
        <h3 class="sv__section-title">Email</h3>
        <p class="sv__section-desc">Configura IMAP/SMTP a runtime usando il keyring locale per la password</p>
    </div>

    <div class="sv__group">
        <div class="sv__row">
            <div class="sv__row-text">
                <span class="sv__row-label">Email Assistant</span>
                <span class="sv__row-hint">Abilita lettura e invio email locali tramite plugin</span>
            </div>
            <button class="sv__toggle" :class="{ 'sv__toggle--on': email.enabled }" role="switch"
                :aria-checked="email.enabled" @click="email.enabled = !email.enabled">
                <span class="sv__toggle-thumb" />
            </button>
        </div>

        <div class="sv__divider" />

        <div class="sv__row">
            <div class="sv__row-text">
                <span class="sv__row-label">Stato servizio</span>
                <span class="sv__row-hint">Connessione IMAP attiva nel backend</span>
            </div>
            <span class="sv__readonly-pill" :class="{ 'sv__readonly-pill--on': email.serviceRunning }">
                {{ email.serviceRunning ? 'Connesso' : 'Non connesso' }}
            </span>
        </div>

        <div class="sv__divider" />

        <div class="sv__row">
            <div class="sv__row-text">
                <span class="sv__row-label">Password nel keyring</span>
                <span class="sv__row-hint">La password non viene salvata nel file config o nel database</span>
            </div>
            <span class="sv__readonly-pill" :class="{ 'sv__readonly-pill--on': email.passwordConfigured }">
                {{ email.passwordConfigured ? 'Salvata' : 'Da inserire' }}
            </span>
        </div>
    </div>

    <div class="sv__fields">
        <label class="sv__field">
            <span class="sv__field-label">Username</span>
            <div class="sv__input-wrap">
                <input v-model.trim="email.username" type="email" class="sv__input" autocomplete="username" />
            </div>
        </label>
        <label class="sv__field">
            <span class="sv__field-label">Password / App password</span>
            <div class="sv__input-wrap">
                <input v-model="email.password" type="password" class="sv__input" autocomplete="current-password" />
            </div>
        </label>
        <label class="sv__field">
            <span class="sv__field-label">IMAP host</span>
            <div class="sv__input-wrap">
                <input v-model.trim="email.imapHost" type="text" class="sv__input" placeholder="imap.example.com" />
            </div>
        </label>
        <label class="sv__field">
            <span class="sv__field-label">IMAP porta</span>
            <div class="sv__input-wrap">
                <input v-model.number="email.imapPort" type="number" class="sv__input" min="1" max="65535" />
            </div>
        </label>
        <label class="sv__field">
            <span class="sv__field-label">SMTP host</span>
            <div class="sv__input-wrap">
                <input v-model.trim="email.smtpHost" type="text" class="sv__input" placeholder="smtp.example.com" />
            </div>
        </label>
        <label class="sv__field">
            <span class="sv__field-label">SMTP porta</span>
            <div class="sv__input-wrap">
                <input v-model.number="email.smtpPort" type="number" class="sv__input" min="1" max="65535" />
            </div>
        </label>
        <label class="sv__field">
            <span class="sv__field-label">Email recenti</span>
            <div class="sv__input-wrap">
                <input v-model.number="email.fetchLastN" type="number" class="sv__input" min="1" max="500" />
            </div>
        </label>
        <label class="sv__field">
            <span class="sv__field-label">Cartella archivio</span>
            <div class="sv__input-wrap">
                <input v-model.trim="email.archiveFolder" type="text" class="sv__input" />
            </div>
        </label>
    </div>

    <div class="sv__group">
        <div class="sv__row">
            <div class="sv__row-text">
                <span class="sv__row-label">IMAP SSL</span>
                <span class="sv__row-hint">Usa TLS diretto per la connessione IMAP</span>
            </div>
            <button class="sv__toggle" :class="{ 'sv__toggle--on': email.imapSsl }" role="switch"
                :aria-checked="email.imapSsl" @click="email.imapSsl = !email.imapSsl">
                <span class="sv__toggle-thumb" />
            </button>
        </div>
        <div class="sv__divider" />
        <div class="sv__row">
            <div class="sv__row-text">
                <span class="sv__row-label">SMTP SSL</span>
                <span class="sv__row-hint">Usa TLS diretto per SMTP; disattivo usa STARTTLS</span>
            </div>
            <button class="sv__toggle" :class="{ 'sv__toggle--on': email.smtpSsl }" role="switch"
                :aria-checked="email.smtpSsl" @click="email.smtpSsl = !email.smtpSsl">
                <span class="sv__toggle-thumb" />
            </button>
        </div>
        <div class="sv__divider" />
        <div class="sv__row">
            <div class="sv__row-text">
                <span class="sv__row-label">IMAP IDLE</span>
                <span class="sv__row-hint">Mantiene una connessione in ascolto per nuove email</span>
            </div>
            <button class="sv__toggle" :class="{ 'sv__toggle--on': email.imapIdleEnabled }" role="switch"
                :aria-checked="email.imapIdleEnabled" @click="email.imapIdleEnabled = !email.imapIdleEnabled">
                <span class="sv__toggle-thumb" />
            </button>
        </div>
    </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useSettingsStore } from '../../stores/settings'

const settingsStore = useSettingsStore()
const email = computed(() => settingsStore.settings.email)
</script>

<style src="../../assets/styles/settings-controls.css"></style>
