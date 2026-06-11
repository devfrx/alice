/**
 * Email-related types aligned with EmailService REST API.
 * Mirrors the dict shapes returned by EmailService methods.
 */

/** Email header returned by GET /api/email/inbox and search. */
export interface EmailHeader {
  uid: string
  subject: string
  from: string
  to: string
  date: string
  message_id: string
  is_read: boolean
  has_attachments: boolean
}

/** Full email with body returned by GET /api/email/{uid}. */
export interface EmailDetail extends EmailHeader {
  cc: string
  body: string
}

/** Payload for POST /api/email/search. */
export interface EmailSearchRequest {
  query: string
  folder?: string
  limit?: number
}

import type { ApiSchema } from './generated'

/** Generated from the backend WS contract — do not redefine locally. */
export type WsEmailReceivedMessage = ApiSchema<'WsEmailReceived'>
export type WsEmailSentMessage = ApiSchema<'WsEmailSent'>
