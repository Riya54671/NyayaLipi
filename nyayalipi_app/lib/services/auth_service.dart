// lib/services/auth_service.dart
//
// Talks to the FastAPI auth endpoints and keeps the JWT + basic user info
// in SharedPreferences so the app can stay logged in between launches.
//
//   POST /auth/signup  → {username, email, password}
//   POST /auth/login   → {email, password}
//   POST /auth/google  → {id_token}   (handles both sign-up and sign-in)
//   GET  /auth/me
//
// All three auth calls return: { access_token, token_type, user: {...} }

import 'dart:convert';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'api_service.dart';

class AuthService {
  static const String _tokenKey = 'auth_token';
  static const String _usernameKey = 'auth_username';
  static const String _emailKey = 'auth_email';
  static const String _webClientId =
    '915785312697-stnkt8ntqp0uilkfc308s44pt178643d.apps.googleusercontent.com';

    // Web reads the client ID from the <meta name="google-signin-client_id">
  // tag in web/index.html instead — serverClientId isn't supported there
  // and throws if passed. Android/iOS need serverClientId so the token
  // returned is audienced for the backend's GOOGLE_CLIENT_ID.
  static final GoogleSignIn _googleSignIn = kIsWeb
      ? GoogleSignIn(scopes: ['email'])
      : GoogleSignIn(scopes: ['email'], serverClientId: _webClientId);
  

  // ── SIGN UP (email/password) ──────────────────────────────────────────
  static Future<void> signUp({
    required String username,
    required String email,
    required String password,
  }) async {
    final response = await http.post(
      Uri.parse('${ApiService.BASE_URL}/auth/signup'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'username': username,
        'email': email,
        'password': password,
      }),
    );
    await _handleAuthResponse(response);
  }

  // ── LOG IN (email/password) ───────────────────────────────────────────
  static Future<void> logIn({
    required String email,
    required String password,
  }) async {
    final response = await http.post(
      Uri.parse('${ApiService.BASE_URL}/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'email': email, 'password': password}),
    );
    await _handleAuthResponse(response);
  }

  // ── SIGN IN / SIGN UP WITH GOOGLE ─────────────────────────────────────
  // One backend endpoint handles both cases: new Google users are created
  // automatically on first sign-in.
  static Future<void> signInWithGoogle() async {
    final googleUser = await _googleSignIn.signIn();
    if (googleUser == null) {
      throw Exception('Google sign-in was cancelled');
    }

    final googleAuth = await googleUser.authentication;
    final idToken = googleAuth.idToken;
    if (idToken == null) {
      throw Exception('Could not get Google ID token');
    }

    final response = await http.post(
      Uri.parse('${ApiService.BASE_URL}/auth/google'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'id_token': idToken}),
    );
    await _handleAuthResponse(response);
  }
    // ── WEB-ONLY: complete sign-in after Google's own rendered button fires ──
  // On web, `.signIn()` can't return an idToken (Google's own limitation).
  // Instead we render Google's actual button and listen for the resulting
  // account via `onCurrentUserChanged`, which DOES carry an idToken.
  static Stream<GoogleSignInAccount?> get onGoogleUserChanged =>
      _googleSignIn.onCurrentUserChanged;

  static Future<void> completeGoogleSignInFromAccount(
    GoogleSignInAccount account,
  ) async {
    final googleAuth = await account.authentication;
    final idToken = googleAuth.idToken;
    if (idToken == null) {
      throw Exception('Could not get Google ID token');
    }

    final response = await http.post(
      Uri.parse('${ApiService.BASE_URL}/auth/google'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'id_token': idToken}),
    );
    await _handleAuthResponse(response);
  }

  // ── LOG OUT ────────────────────────────────────────────────────────────
  static Future<void> logOut() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_tokenKey);
    await prefs.remove(_usernameKey);
    await prefs.remove(_emailKey);
    try {
      await _googleSignIn.signOut();
    } catch (_) {
      // no-op — user may not have signed in with Google
    }
  }

  // ── SESSION HELPERS ───────────────────────────────────────────────────
  static Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_tokenKey);
  }

  static Future<bool> isLoggedIn() async {
    final token = await getToken();
    return token != null && token.isNotEmpty;
  }

  static Future<String?> getUsername() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_usernameKey);
  }

  static Future<String?> getEmail() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_emailKey);
  }

  // Convenience for other services (e.g. ApiService) to attach the token.
  static Future<Map<String, String>> authHeader() async {
    final token = await getToken();
    if (token == null) return {};
    return {'Authorization': 'Bearer $token'};
  }

  // ── INTERNAL ───────────────────────────────────────────────────────────
  static Future<void> _handleAuthResponse(http.Response response) async {
    final data = jsonDecode(response.body);

    if (response.statusCode != 200) {
      throw Exception(data['detail']?.toString() ?? 'Authentication failed');
    }

    final token = data['access_token'] as String;
    final user = data['user'] as Map<String, dynamic>;

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, token);
    await prefs.setString(_usernameKey, user['username'] ?? '');
    await prefs.setString(_emailKey, user['email'] ?? '');
  }
}