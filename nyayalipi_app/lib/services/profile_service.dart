import 'dart:convert';
import 'package:http/http.dart' as http;
import 'api_service.dart';
import 'auth_service.dart';

class ProfileService {
  static Future<Map<String, String>> _headers() async {
    final token = await AuthService.getToken();
    return {
      'Authorization': 'Bearer $token',
      'Content-Type': 'application/json',
    };
  }

  static dynamic _decode(http.Response res) {
    final body = jsonDecode(utf8.decode(res.bodyBytes));
    if (res.statusCode >= 200 && res.statusCode < 300) return body;
    final detail = body is Map && body['detail'] != null
        ? body['detail'].toString()
        : 'Request failed (${res.statusCode})';
    throw Exception(detail);
  }

  static Future<Map<String, dynamic>> getMe() async {
    final res = await http.get(Uri.parse('${ApiService.BASE_URL}/auth/me'),
        headers: await _headers());
    return Map<String, dynamic>.from(_decode(res));
  }

  static Future<List<dynamic>> getFiles() async {
    final res = await http.get(Uri.parse('${ApiService.BASE_URL}/me/files'),
        headers: await _headers());
    return List<dynamic>.from(_decode(res));
  }

  static Future<List<dynamic>> getGlossary(String fileId) async {
    final res = await http.get(
        Uri.parse('${ApiService.BASE_URL}/files/$fileId/glossary'),
        headers: await _headers());
    return List<dynamic>.from(_decode(res));
  }

  static Future<Map<String, dynamic>> updateMe({
    String? username,
    String? email,
    String? newPassword,
  }) async {
    final res = await http.put(
      Uri.parse('${ApiService.BASE_URL}/auth/me'),
      headers: await _headers(),
      body: jsonEncode({
        'username': ?username,
        'email': ?email,
        if (newPassword != null && newPassword.isNotEmpty)
          'new_password': newPassword,
      }),
    );
    return Map<String, dynamic>.from(_decode(res));
  }
}