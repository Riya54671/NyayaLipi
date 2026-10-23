import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme/app_theme.dart';
import '../services/auth_service.dart';
import 'dashboard_screen.dart';
import 'signup_screen.dart';
import 'dart:async';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:google_sign_in/google_sign_in.dart';
import 'google_web_button_stub.dart'
    if (dart.library.html) 'google_web_button_web.dart' as web_only;

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  StreamSubscription<GoogleSignInAccount?>? _googleSub;
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _isLoading = false;
  bool _obscurePassword = true;
  String? _errorMessage;
    @override
  void initState() {
    super.initState();
    if (kIsWeb) {
      _googleSub = AuthService.onGoogleUserChanged.listen((account) async {
        if (account == null) return;
        setState(() {
          _isLoading = true;
          _errorMessage = null;
        });
        try {
          await AuthService.completeGoogleSignInFromAccount(account);
          _goToDashboard();
        } catch (e) {
          setState(() =>
              _errorMessage = e.toString().replaceFirst('Exception: ', ''));
        } finally {
          if (mounted) setState(() => _isLoading = false);
        }
      });
    }
  }

   @override
  void dispose() {
    _googleSub?.cancel();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _login() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });
    try {
      await AuthService.logIn(
        email: _emailController.text.trim(),
        password: _passwordController.text,
      );
      _goToDashboard();
    } catch (e) {
      setState(() => _errorMessage = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _loginWithGoogle() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });
    try {
      await AuthService.signInWithGoogle();
      _goToDashboard();
    } catch (e) {
      setState(() => _errorMessage = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _goToDashboard() {
    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (_) => const DashboardScreen()),
    );
  }

  void _forgotPasswordTapped() {
    // No backend endpoint for this yet — wire this up to a
    // POST /auth/forgot-password route when you add one.
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Password reset isn\'t set up yet.')),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.white,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  const SizedBox(height: 12),
                  Text(
                    'Login',
                    textAlign: TextAlign.center,
                    style: GoogleFonts.dmSans(
                      fontSize: 40,
                      fontWeight: FontWeight.w800,
                      color: AppTheme.primaryBlue,
                    ),
                  ).animate().fadeIn(duration: 500.ms).slideY(begin: -0.15, end: 0),
                  const SizedBox(height: 6),
                  Text(
                    'Please login to continue',
                    style: GoogleFonts.poppins(
                      fontSize: 14,
                      color: AppTheme.textGrey,
                    ),
                  ),
                  const SizedBox(height: 28),

                  // ── Card ──────────────────────────────────────────────
                  Container(
                    padding: const EdgeInsets.fromLTRB(20, 26, 20, 26),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(28),
                      border: Border.all(color: Colors.grey.shade200),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withValues(alpha: 0.06),
                          blurRadius: 20,
                          offset: const Offset(0, 8),
                        ),
                      ],
                    ),
                    child: Column(
                      children: [
                        TextFormField(
                          controller: _emailController,
                          keyboardType: TextInputType.emailAddress,
                          decoration: _pillDecoration('Enter Username/Email'),
                          validator: (v) {
                            if (v == null || v.trim().isEmpty) {
                              return 'Enter your email';
                            }
                            if (!v.contains('@')) return 'Enter a valid email';
                            return null;
                          },
                        ),
                        const SizedBox(height: 14),

                        TextFormField(
                          controller: _passwordController,
                          obscureText: _obscurePassword,
                          decoration: _pillDecoration('Password').copyWith(
                            suffixIcon: IconButton(
                              icon: Icon(
                                _obscurePassword
                                    ? Icons.visibility_off_outlined
                                    : Icons.visibility_outlined,
                                color: AppTheme.textGrey,
                                size: 20,
                              ),
                              onPressed: () => setState(
                                  () => _obscurePassword = !_obscurePassword),
                            ),
                          ),
                          validator: (v) {
                            if (v == null || v.isEmpty) return 'Enter your password';
                            return null;
                          },
                        ),

                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton(
                            onPressed: _isLoading ? null : _forgotPasswordTapped,
                            style: TextButton.styleFrom(
                              padding: EdgeInsets.zero,
                              minimumSize: const Size(0, 32),
                              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                            ),
                            child: Text(
                              'Forgot Password ?',
                              style: GoogleFonts.poppins(
                                fontSize: 12,
                                color: AppTheme.primaryBlue,
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                          ),
                        ),

                        if (_errorMessage != null) ...[
                          const SizedBox(height: 4),
                          Text(
                            _errorMessage!,
                            style: GoogleFonts.poppins(
                              fontSize: 12,
                              color: Colors.red.shade600,
                            ),
                          ),
                        ],

                        const SizedBox(height: 6),
                        Row(
                          children: [
                            Expanded(child: Divider(color: Colors.grey.shade300)),
                            Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 10),
                              child: Text('OR',
                                  style: GoogleFonts.poppins(
                                      fontSize: 11, color: AppTheme.textGrey)),
                            ),
                            Expanded(child: Divider(color: Colors.grey.shade300)),
                          ],
                        ),
                        const SizedBox(height: 14),

                                                                        if (kIsWeb)
                          SizedBox(
                            width: double.infinity,
                            height: 48,
                            child: web_only.renderButton(
                              configuration: web_only.GSIButtonConfiguration(
                                type: web_only.GSIButtonType.standard,
                                theme: web_only.GSIButtonTheme.filledBlue,
                                size: web_only.GSIButtonSize.large,
                                text: web_only.GSIButtonText.signinWith,
                                shape: web_only.GSIButtonShape.pill,
                                logoAlignment: web_only.GSIButtonLogoAlignment.left,
                                minimumWidth: 300,
                              ),
                            ),
                          )
                        else
                          SizedBox(
                            width: double.infinity,
                            child: OutlinedButton.icon(
                              onPressed: _isLoading ? null : _loginWithGoogle,
                              icon: const Icon(Icons.g_mobiledata_rounded,
                                  size: 26, color: Color(0xFF4285F4)),
                              label: Text(
                                'Login using Google',
                                style: GoogleFonts.poppins(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                  color: AppTheme.primaryBlue,
                                ),
                              ),
                              style: OutlinedButton.styleFrom(
                                backgroundColor: const Color(0xFFF3F4F6),
                                side: BorderSide(color: Colors.grey.shade300),
                                padding: const EdgeInsets.symmetric(vertical: 13),
                                shape: const StadiumBorder(),
                              ),
                            ),
                          ),
                        const SizedBox(height: 20),

                        SizedBox(
                          width: double.infinity,
                          child: ElevatedButton(
                            onPressed: _isLoading ? null : _login,
                            style: ElevatedButton.styleFrom(
                              padding: const EdgeInsets.symmetric(vertical: 14),
                            ),
                            child: _isLoading
                                ? const SizedBox(
                                    height: 20,
                                    width: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2.4,
                                      color: Colors.white,
                                    ),
                                  )
                                : Text(
                                    'LOGIN',
                                    style: GoogleFonts.poppins(
                                      fontWeight: FontWeight.w800,
                                      letterSpacing: 1.0,
                                    ),
                                  ),
                          ),
                        ),
                        const SizedBox(height: 12),

                        GestureDetector(
                          onTap: _isLoading
                              ? null
                              : () {
                                  Navigator.pushReplacement(
                                    context,
                                    MaterialPageRoute(
                                      builder: (_) => const SignupScreen(),
                                    ),
                                  );
                                },
                          child: RichText(
                            text: TextSpan(
                              style: GoogleFonts.poppins(
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                                color: AppTheme.textDark,
                              ),
                              children: [
                                const TextSpan(text: 'Not an user ? '),
                                TextSpan(
                                  text: 'Sign up',
                                  style: TextStyle(color: AppTheme.primaryBlue),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  InputDecoration _pillDecoration(String hint) => InputDecoration(
        hintText: hint,
        hintStyle: GoogleFonts.poppins(color: Colors.grey.shade500, fontSize: 13),
        contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(30),
          borderSide: BorderSide(color: Colors.grey.shade300),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(30),
          borderSide: BorderSide(color: Colors.grey.shade300),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(30),
          borderSide: BorderSide(color: AppTheme.primaryBlue, width: 1.6),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(30),
          borderSide: BorderSide(color: Colors.red.shade300),
        ),
      );
}