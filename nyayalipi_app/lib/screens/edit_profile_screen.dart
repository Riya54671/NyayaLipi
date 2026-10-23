import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme/app_theme.dart';
import '../services/auth_service.dart';
import '../services/profile_service.dart';

class EditProfileScreen extends StatefulWidget {
  final Map<String, dynamic> me;
  const EditProfileScreen({super.key, required this.me});

  @override
  State<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends State<EditProfileScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _email;
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  bool _saving = false;
  bool _obscurePass = true;
  bool _obscureConfirm = true;
  String? _error;
  String? _success;

  static final RegExp _strongPassword =
      RegExp(r'^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>_\-]).{8,}$');

  bool get _isGoogle => widget.me['auth_provider'] == 'google';

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.me['username'] ?? '');
    _email = TextEditingController(text: widget.me['email'] ?? '');
  }

  @override
  void dispose() {
    _name.dispose(); _email.dispose(); _password.dispose(); _confirm.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() { _saving = true; _error = null; _success = null; });
    try {
      final changingPassword = !_isGoogle && _password.text.isNotEmpty;
      final updated = await ProfileService.updateMe(
        username: _name.text.trim(),
        email: _email.text.trim(),
        newPassword: changingPassword ? _password.text : null,
      );
      await AuthService.updateCachedUser(
        username: updated['username'],
        email: updated['email'],
      );
      if (!mounted) return;
      setState(() {
        _success = changingPassword ? 'Password changed successfully' : 'Profile updated';
        _password.clear();
        _confirm.clear();
      });
      await Future.delayed(const Duration(milliseconds: 1200));
      if (mounted) Navigator.pop(context, true); // true → profile reloads
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  InputDecoration _dec(String label, {Widget? suffix}) => InputDecoration(
        labelText: label,
        labelStyle: GoogleFonts.poppins(fontSize: 12, color: AppTheme.textGrey),
        border: InputBorder.none,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        suffixIcon: suffix,
      );

  Widget _eye(bool obscure, VoidCallback onTap) => IconButton(
        icon: Icon(obscure ? Icons.visibility_off_outlined : Icons.visibility_outlined,
            size: 20, color: AppTheme.textGrey),
        onPressed: _isGoogle ? null : onTap,
      );

  @override
  Widget build(BuildContext context) {
    final contentWidth = math.min(420.0, MediaQuery.of(context).size.width - 40);

    final fields = <Widget>[
      TextFormField(
        controller: _name,
        style: GoogleFonts.poppins(fontSize: 14),
        decoration: _dec('Name'),
        validator: (v) => (v == null || v.trim().length < 3) ? 'At least 3 characters' : null,
      ),
      TextFormField(
        controller: _email,
        keyboardType: TextInputType.emailAddress,
        style: GoogleFonts.poppins(fontSize: 14),
        decoration: _dec('E-mail'),
        validator: (v) => (v == null || !v.contains('@')) ? 'Enter a valid email' : null,
      ),
      TextFormField(
        controller: _password,
        enabled: !_isGoogle,
        obscureText: _obscurePass,
        style: GoogleFonts.poppins(fontSize: 14),
        decoration: _dec('New Password',
            suffix: _eye(_obscurePass, () => setState(() => _obscurePass = !_obscurePass))),
        validator: (v) {
          if (_isGoogle || v == null || v.isEmpty) return null;
          return _strongPassword.hasMatch(v)
              ? null
              : '8+ chars, 1 uppercase, 1 number, 1 special';
        },
      ),
      TextFormField(
        controller: _confirm,
        enabled: !_isGoogle,
        obscureText: _obscureConfirm,
        style: GoogleFonts.poppins(fontSize: 14),
        decoration: _dec('Confirm Password',
            suffix: _eye(_obscureConfirm, () => setState(() => _obscureConfirm = !_obscureConfirm))),
        validator: (v) {
          if (_isGoogle || _password.text.isEmpty) return null;
          return v != _password.text ? 'Passwords do not match' : null;
        },
      ),
    ];

    return Scaffold(
      backgroundColor: AppTheme.white,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Align(
            alignment: Alignment.topCenter,
            child: SizedBox(
              width: contentWidth,
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // ── Header ─────────────────────────────────────
                    Row(children: [
                      IconButton(
                        icon: const Icon(Icons.arrow_back),
                        onPressed: () => Navigator.pop(context),
                      ),
                      Expanded(
                        child: Text('Edit Profile',
                            textAlign: TextAlign.center,
                            style: GoogleFonts.poppins(fontSize: 24,
                                fontWeight: FontWeight.w800,
                                color: AppTheme.primaryBlue)),
                      ),
                      const SizedBox(width: 48), // balances the back button
                    ]).animate().fadeIn(duration: 400.ms),

                    const SizedBox(height: 12),
                    Center(
                      child: CircleAvatar(
                        radius: 34,
                        backgroundColor: Colors.grey.shade500,
                        child: const Icon(Icons.person, size: 40, color: Colors.white),
                      ),
                    ),
                    const SizedBox(height: 24),

                    // ── Fields card ────────────────────────────────
                    Container(
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.grey.shade300),
                        boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.05),
                            blurRadius: 8, offset: const Offset(0, 2))],
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          for (int i = 0; i < fields.length; i++) ...[
                            fields[i],
                            if (i < fields.length - 1)
                              Divider(height: 1, color: Colors.grey.shade200),
                          ],
                        ],
                      ),
                    ).animate().fadeIn(delay: 100.ms),

                    const SizedBox(height: 8),
                    Text(
                      _isGoogle
                          ? 'You signed in with Google, so there is no password to change.'
                          : 'Leave password blank to keep your current one.',
                      textAlign: TextAlign.left,
                      style: GoogleFonts.poppins(fontSize: 11, color: AppTheme.textGrey),
                    ),

                    const SizedBox(height: 20),

                    if (_error != null) ...[
                      Text(_error!,
                          textAlign: TextAlign.left,
                          style: GoogleFonts.poppins(fontSize: 12, color: Colors.red.shade600)),
                      const SizedBox(height: 12),
                    ],
                    if (_success != null) ...[
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                        decoration: BoxDecoration(
                          color: AppTheme.lightBlue,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(_success!,
                            textAlign: TextAlign.center,
                            style: GoogleFonts.poppins(fontSize: 13,
                                fontWeight: FontWeight.w700, color: AppTheme.textDark)),
                      ).animate().fadeIn(duration: 300.ms),
                      const SizedBox(height: 12),
                    ],

                    ElevatedButton(
                      onPressed: _saving ? null : _save,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.primaryBlue,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12)),
                      ),
                      child: _saving
                          ? const SizedBox(height: 20, width: 20,
                              child: CircularProgressIndicator(
                                  color: Colors.white, strokeWidth: 2))
                          : Text('Save',
                              style: GoogleFonts.poppins(fontWeight: FontWeight.w700,
                                  fontSize: 16, color: AppTheme.white)),
                    ),
                    const SizedBox(height: 24),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}