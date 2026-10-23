import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme/app_theme.dart';
import '../services/auth_service.dart';
import '../services/profile_service.dart';
import 'edit_profile_screen.dart';
import 'landing_screen.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Map<String, dynamic>? _me;
  List<dynamic> _files = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final results = await Future.wait([
        ProfileService.getMe(),
        ProfileService.getFiles(),
      ]);
      if (!mounted) return;
      setState(() {
        _me = results[0] as Map<String, dynamic>;
        _files = results[1] as List<dynamic>;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString().replaceFirst('Exception: ', '');
        _loading = false;
      });
    }
  }

  Future<void> _logout() async {
    await AuthService.logOut();
    if (!mounted) return;
    Navigator.pushAndRemoveUntil(
      context,
      MaterialPageRoute(builder: (_) => const LandingScreen()),
      (route) => false,
    );
  }

  Future<void> _openEdit() async {
    final updated = await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => EditProfileScreen(me: _me ?? {})),
    );
    if (updated == true) _load();
  }

  String _fmtDate(String? iso) {
    if (iso == null) return '-';
    final d = DateTime.tryParse(iso)?.toLocal();
    if (d == null) return '-';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(d.day)}/${two(d.month)}/${d.year}';
  }

  // Tap a row → show that document's glossary
  void _openFileGlossary(dynamic f) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTheme.white,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.6,
        maxChildSize: 0.95,
        builder: (_, controller) => FutureBuilder<List<dynamic>>(
          future: ProfileService.getGlossary(f['file_id']),
          builder: (context, snap) {
            Widget body;
            if (snap.connectionState != ConnectionState.done) {
              body = const Center(child: CircularProgressIndicator());
            } else if (snap.hasError) {
              body = Center(child: Text('Could not load glossary',
                  style: GoogleFonts.poppins(color: AppTheme.textGrey)));
            } else if ((snap.data ?? []).isEmpty) {
              body = Center(child: Text('No legal terms in this document',
                  style: GoogleFonts.poppins(color: AppTheme.textGrey)));
            } else {
              final terms = snap.data!;
              body = ListView.separated(
                controller: controller,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: terms.length,
                separatorBuilder: (_, _) =>
                    Divider(height: 1, color: Colors.grey.shade200),
                itemBuilder: (_, i) => Theme(
                  data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                  child: ExpansionTile(
                    tilePadding: const EdgeInsets.symmetric(horizontal: 4),
                    childrenPadding: const EdgeInsets.fromLTRB(4, 0, 4, 10),
                    expandedAlignment: Alignment.centerLeft,
                    iconColor: AppTheme.primaryBlue,
                    title: Text(terms[i]['term'] ?? '',
                        style: GoogleFonts.poppins(fontSize: 13,
                            fontWeight: FontWeight.w600)),
                    children: [
                      Text(terms[i]['text'] ?? '',
                          style: GoogleFonts.poppins(fontSize: 12,
                              color: AppTheme.textGrey, height: 1.5)),
                    ],
                  ),
                ),
              );
            }
            return Column(children: [
              const SizedBox(height: 10),
              Container(width: 40, height: 4,
                  decoration: BoxDecoration(color: Colors.grey.shade300,
                      borderRadius: BorderRadius.circular(2))),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text(f['document_name'] ?? 'Glossary',
                    textAlign: TextAlign.center,
                    style: GoogleFonts.poppins(fontSize: 16,
                        fontWeight: FontWeight.w700, color: AppTheme.primaryBlue)),
              ),
              Expanded(child: body),
            ]);
          },
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final contentWidth = math.min(420.0, MediaQuery.of(context).size.width - 40);

    Widget content;
    if (_loading) {
      content = const Center(child: CircularProgressIndicator());
    } else if (_error != null) {
      content = Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(_error!, style: GoogleFonts.poppins(color: AppTheme.textGrey)),
          TextButton(onPressed: _load, child: const Text('Retry')),
        ]),
      );
    } else {
      content = RefreshIndicator(
        onRefresh: _load,
        child: SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Align(
            alignment: Alignment.topCenter,
            child: SizedBox(
              width: contentWidth,
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
                      child: Text('Profile',
                          textAlign: TextAlign.center,
                          style: GoogleFonts.poppins(fontSize: 26,
                              fontWeight: FontWeight.w800,
                              color: AppTheme.primaryBlue)),
                    ),
                    const SizedBox(width: 48), // balances the back button
                  ]).animate().fadeIn(duration: 400.ms),

                  const SizedBox(height: 12),
                  Center(
                    child: CircleAvatar(
                      radius: 38,
                      backgroundColor: Colors.grey.shade500,
                      child: const Icon(Icons.person, size: 46, color: Colors.white),
                    ),
                  ),
                  const SizedBox(height: 24),

                  // ── Name / Email (no password) ─────────────────
                  _infoCard([
                    _infoRow('Name', _me?['username'] ?? ''),
                    _infoRow('E-mail', _me?['email'] ?? ''),
                  ]).animate().fadeIn(delay: 100.ms),

                  const SizedBox(height: 24),

                  // ── File history table ─────────────────────────
                  Text('Your documents',
                      textAlign: TextAlign.left,
                      style: GoogleFonts.poppins(fontSize: 15,
                          fontWeight: FontWeight.w600, color: AppTheme.textDark)),
                  const SizedBox(height: 8),
                  _filesTable().animate().fadeIn(delay: 150.ms),

                  const SizedBox(height: 28),

                  // ── Buttons ────────────────────────────────────
                  ElevatedButton.icon(
                    onPressed: _openEdit,
                    icon: const Icon(Icons.edit_outlined, size: 18),
                    label: Text('Edit Profile',
                        style: GoogleFonts.poppins(fontWeight: FontWeight.w600)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.primaryBlue,
                      foregroundColor: AppTheme.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: _logout,
                    icon: const Icon(Icons.logout, size: 18, color: Colors.redAccent),
                    label: Text('Logout',
                        style: GoogleFonts.poppins(fontWeight: FontWeight.w600,
                            color: AppTheme.textDark)),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                    ),
                  ),
                  const SizedBox(height: 24),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: AppTheme.white,
      body: SafeArea(child: content),
    );
  }

  Widget _infoCard(List<Widget> rows) => Container(
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
            for (int i = 0; i < rows.length; i++) ...[
              rows[i],
              if (i < rows.length - 1) Divider(height: 1, color: Colors.grey.shade200),
            ],
          ],
        ),
      );

  Widget _infoRow(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label,
                style: GoogleFonts.poppins(fontSize: 11, color: AppTheme.textGrey)),
            const SizedBox(height: 2),
            Text(value.isEmpty ? '-' : value,
                style: GoogleFonts.poppins(fontSize: 14, color: AppTheme.textDark)),
          ],
        ),
      );

  Widget _filesTable() {
    final header = GoogleFonts.poppins(fontSize: 12,
        fontWeight: FontWeight.w700, color: AppTheme.primaryBlue);
    final cell = GoogleFonts.poppins(fontSize: 12, color: AppTheme.textDark);

    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.grey.shade300),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Header row
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: AppTheme.backgroundBlue,
              borderRadius: const BorderRadius.vertical(top: Radius.circular(11)),
            ),
            child: Row(children: [
              SizedBox(width: 40, child: Text('S.No', style: header)),
              Expanded(child: Text('Document', style: header)),
              SizedBox(width: 84,
                  child: Text('Date', style: header, textAlign: TextAlign.right)),
            ]),
          ),
          if (_files.isEmpty)
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text('No documents translated yet.',
                  style: GoogleFonts.poppins(fontSize: 12, color: AppTheme.textGrey)),
            )
          else
            for (int i = 0; i < _files.length; i++)
              InkWell(
                onTap: () => _openFileGlossary(_files[i]),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                  decoration: BoxDecoration(
                    border: Border(top: BorderSide(color: Colors.grey.shade200)),
                  ),
                  child: Row(children: [
                    SizedBox(width: 40, child: Text('${i + 1}', style: cell)),
                    Expanded(
                      child: Text(_files[i]['document_name'] ?? '',
                          maxLines: 1, overflow: TextOverflow.ellipsis, style: cell),
                    ),
                    SizedBox(
                      width: 84,
                      child: Text(_fmtDate(_files[i]['time']),
                          textAlign: TextAlign.right, style: cell),
                    ),
                  ]),
                ),
              ),
        ],
      ),
    );
  }
}