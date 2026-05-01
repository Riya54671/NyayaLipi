// lib/services/api_service.dart
//
// Calls your FastAPI backend endpoints:
//   POST /detect-language  → detects language of uploaded file
//   POST /translate        → full pipeline (extract→RAG→translate→TTS)
//   GET  /download/document/{job_id}
//   GET  /download/audio/{job_id}

import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;


class ApiService {
  // ── Change this if testing on a real phone (use your PC's local IP) ──────
  // Emulator/Chrome: keep as 127.0.0.1
  // Real Android phone on same WiFi: change to e.g. http://192.168.1.5:8000
  static const String BASE_URL = 'http://10.92.168.64:8000';

  // ── 1. DETECT LANGUAGE ────────────────────────────────────────────────────
  // POST /detect-language
  // Sends the file → backend extracts text → Sarvam detects language
  // Returns: { "language": "Tamil" }
 static Future<String> detectLanguage(File file) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$BASE_URL/detect-language'),
    );

    request.files.add(
      await http.MultipartFile.fromPath('file', file.path),
    );

    final streamedResponse = await request.send()
        .timeout(const Duration(seconds: 30)); // ← ADD THIS
    final response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      return data['language'] ?? 'Unknown';
    } else {
      final err = jsonDecode(response.body);
      throw Exception(err['detail'] ?? 'Language detection failed');
    }
  }

  // ── 2. TRANSLATE DOCUMENT ─────────────────────────────────────────────────
  // POST /translate
  // Sends: file + source_language + target_language + tts_speaker + generate_audio
  // Returns: TranslationResponse JSON
  static Future<Map<String, dynamic>> translateDocument({
    required File file,
    required String sourceLanguage,   // e.g. "Tamil"
    required String targetLanguage,   // e.g. "Hindi"
    String ttsSpeaker = 'anushka',
    bool generateAudio = true,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('$BASE_URL/translate'),
    );

    // File attachment
    request.files.add(
      await http.MultipartFile.fromPath('file', file.path),
    );

    // Form fields — must match your FastAPI Form() params exactly
    request.fields['source_language'] = sourceLanguage;
    request.fields['target_language'] = targetLanguage;
    request.fields['tts_speaker']     = ttsSpeaker;
    request.fields['generate_audio']  = generateAudio.toString();

    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode == 200) {
      return jsonDecode(response.body);
      // Returns:
      // {
      //   "job_id": "abc-123",
      //   "source_language": "Tamil",
      //   "target_language": "Hindi",
      //   "translated_text_preview": "...",
      //   "document_download_url": "/download/document/abc-123",
      //   "audio_download_url": "/download/audio/abc-123",
      //   "original_filename": "doc.pdf",
      //   "message": "Translation complete.",
      //   "legal_terms_found": ["affidavit", "injunction"],
      //   "entities_found": { "COURT": ["High Court of Madras"] }
      // }
    } else {
      final err = jsonDecode(response.body);
      throw Exception(err['detail'] ?? 'Translation failed');
    }
  }

  // ── 3. DOWNLOAD DOCUMENT ──────────────────────────────────────────────────
  // GET /download/document/{job_id}
  // Returns the translated file bytes (docx / txt / pdf)
  static Future<List<int>> downloadDocument(String jobId) async {
    final response = await http.get(
      Uri.parse('$BASE_URL/download/document/$jobId'),
    );
    if (response.statusCode == 200) {
      return response.bodyBytes;
    }
    throw Exception('Document download failed: ${response.statusCode}');
  }

  // ── 4. AUDIO URL ──────────────────────────────────────────────────────────
  // GET /download/audio/{job_id}
  // Returns full URL string — pass directly to audioplayers
  static String audioUrl(String jobId) {
    return '$BASE_URL/download/audio/$jobId';
  }

  // ── 5. CHECK BACKEND IS RUNNING ───────────────────────────────────────────
  // GET /  → quick health check before doing anything
  static Future<bool> isBackendRunning() async {
    try {
      final response = await http.get(
        Uri.parse('$BASE_URL/'),
      ).timeout(const Duration(seconds: 5));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}