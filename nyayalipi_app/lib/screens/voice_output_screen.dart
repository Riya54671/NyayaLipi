import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:just_audio/just_audio.dart';
import 'package:path_provider/path_provider.dart';
import 'dart:io';
import 'dart:convert';
import '../theme/app_theme.dart';
import '../services/api_service.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:share_plus/share_plus.dart';

class VoiceOutputScreen extends StatefulWidget {
  final String sourceLanguage;
  final String targetLanguage;
  final String translatedText;  // text returned by backend (English / target lang)
  final String audioBase64;
  final String docUrl;


  const VoiceOutputScreen({super.key, 
  required this.sourceLanguage,
  required this.targetLanguage,
  required this.translatedText,
  required this.audioBase64,
  required this.docUrl,
});

  @override
  State<VoiceOutputScreen> createState() => _VoiceOutputScreenState();
}

class _VoiceOutputScreenState extends State<VoiceOutputScreen> {
  late final AudioPlayer _player;
  bool   _isPlaying        = false;
  bool   _isAudioReady     = false;
  Duration _duration       = Duration.zero;
  Duration _position       = Duration.zero;
  bool   _showDlNotif      = false;
  String? _savedAudioPath;

  @override
void initState() {
  super.initState();
  print('[DEBUG] VoiceOutputScreen docUrl: "${widget.docUrl}"'); // ← ADD
  print('[DEBUG] VoiceOutputScreen audioUrl: "${widget.audioBase64}"'); // ← ADD
  _player = AudioPlayer();
  _initAudio();
  _listenToPlayer();
}

  // ── Decode base64 WAV → temp file → load into player ───────────────────
  Future<void> _initAudio() async {
  try {
    await _player.setUrl(widget.audioBase64);
    if (mounted) setState(() => _isAudioReady = true);
  } catch (e) {
    debugPrint('Audio init error: $e');
  }
}

  void _listenToPlayer() {
    _player.durationStream.listen((d) {
      if (mounted && d != null) setState(() => _duration = d);
    });
    _player.positionStream.listen((p) {
      if (mounted) setState(() => _position = p);
    });
    _player.playerStateStream.listen((s) {
      if (mounted) {
        setState(() => _isPlaying = s.playing);
        if (s.processingState == ProcessingState.completed) {
          setState(() { _isPlaying = false; _position = Duration.zero; });
          _player.seek(Duration.zero);
        }
      }
    });
  }

  Future<void> _togglePlay() async {
    if (!_isAudioReady) return;
    _isPlaying ? await _player.pause() : await _player.play();
  }

  Future<void> _seekTo(double v) async {
    await _player.seek(
        Duration(milliseconds: (v * _duration.inMilliseconds).toInt()));
  }

Future<void> _handleDownload() async {
  print('[DEBUG] _handleDownload called, docUrl: "${widget.docUrl}"');
  try {
    if (widget.docUrl.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text('No document available.',
            style: GoogleFonts.poppins(fontSize: 12)),
        backgroundColor: Colors.redAccent,
      ));
      return;
    }

    final uri = Uri.parse(widget.docUrl);
    // ← Don't use canLaunchUrl, just launch directly
    await launchUrl(uri, mode: LaunchMode.externalApplication);
    
    setState(() => _showDlNotif = true);
    Future.delayed(const Duration(seconds: 3), () {
      if (mounted) setState(() => _showDlNotif = false);
    });
  } catch (e) {
    debugPrint('Download error: $e');
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text('Download failed: $e',
          style: GoogleFonts.poppins(fontSize: 12)),
      backgroundColor: Colors.redAccent,
    ));
  }
}
  Future<void> _handleShare() async {
  try {
    // Share the document URL if available
    if (widget.docUrl.isNotEmpty) {
      await Share.share(
        'Check out my translated document: ${widget.docUrl}',
        subject: 'Translated Document',
      );
      return;
    }

    // Fallback: share the translated text
    if (widget.translatedText.isNotEmpty) {
      await Share.share(
        widget.translatedText,
        subject: 'Translated Text',
      );
      return;
    }

    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text('Nothing to share.',
          style: GoogleFonts.poppins(fontSize: 12)),
      backgroundColor: Colors.redAccent,
    ));
  } catch (e) {
    debugPrint('Share error: $e');
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text('Share failed: $e',
          style: GoogleFonts.poppins(fontSize: 12)),
      backgroundColor: Colors.redAccent,
    ));
  }
}
  String _fmt(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }
  double get _sliderVal {
    if (_duration.inMilliseconds == 0) return 0.0;
    return (_position.inMilliseconds / _duration.inMilliseconds).clamp(0.0, 1.0);
  }
  @override
  void dispose() { _player.dispose(); super.dispose(); }
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.white,
      body: SafeArea(
        child: Stack(
          children: [
            SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [

                  // ── Header ───────────────────────────────────────────
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Expanded(
                        child: Text("Here's your translated document!",
                            style: GoogleFonts.poppins(fontSize: 22,
                                fontWeight: FontWeight.w800,
                                color: AppTheme.primaryBlue)),
                      ),
                      const SizedBox(width: 8),
                      
                    ],
                  ).animate().fadeIn(duration: 500.ms),

                  const SizedBox(height: 8),

                  // ── Section label ─────────────────────────────────────
                  Row(children: [
                    _circleIcon(Icons.download_outlined),
                    const SizedBox(width: 10),
                    Column(crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Download Document',
                            style: GoogleFonts.poppins(
                                fontWeight: FontWeight.w600, fontSize: 15)),
                        Text('Download and save your translated document',
                            style: GoogleFonts.poppins(
                                fontSize: 11, color: AppTheme.textGrey)),
                      ],
                    ),
                  ]).animate().fadeIn(delay: 100.ms),

                  const Divider(height: 20),

                  // ── Big Download Box ──────────────────────────────────
                  GestureDetector(
                    onTap: _handleDownload,
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                          color: AppTheme.backgroundBlue,
                          borderRadius: BorderRadius.circular(16)),
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 28),
                        decoration: BoxDecoration(
                          border: Border.all(
                              color: AppTheme.primaryBlue.withOpacity(0.4),
                              width: 1.5),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Column(children: [
                          const Icon(Icons.download_rounded,
                              size: 40, color: AppTheme.textDark),
                          const SizedBox(height: 12),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 24, vertical: 10),
                            decoration: BoxDecoration(
                                color: AppTheme.textDark,
                                borderRadius: BorderRadius.circular(8)),
                            child: Text('Download',
                                style: GoogleFonts.poppins(
                                    color: AppTheme.white,
                                    fontSize: 14,
                                    fontWeight: FontWeight.w600)),
                          ),
                        ]),
                      ),
                    ),
                  ).animate().fadeIn(delay: 150.ms),

                  const SizedBox(height: 20),

                  // ── Action row ────────────────────────────────────────
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                    children: [
                      _actionBtn(icon: Icons.download_outlined,
                          label: 'Download', onTap: _handleDownload),
                      _actionBtn(icon: Icons.share_outlined,
                          label: 'Share',    onTap: _handleShare),
                      _actionBtn(icon: Icons.record_voice_over_outlined,
                          label: 'Voice',   onTap: _togglePlay),
                    ],
                  ).animate().fadeIn(delay: 200.ms),

                  const SizedBox(height: 20),

                  // ── Translated text card ──────────────────────────────
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      border: Border.all(
                          color: AppTheme.primaryBlue.withOpacity(0.3)),
                      borderRadius: BorderRadius.circular(12),
                      color: AppTheme.white,
                      boxShadow: [BoxShadow(
                          color: Colors.black.withOpacity(0.04),
                          blurRadius: 8, offset: const Offset(0, 2))],
                    ),
                    child: _highlightedText(widget.translatedText),
                  ).animate().fadeIn(delay: 250.ms),

                  const SizedBox(height: 20),

                  // ── Audio Player ──────────────────────────────────────
                  Column(children: [
                    if (!_isAudioReady)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const SizedBox(width: 14, height: 14,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: AppTheme.primaryBlue)),
                            const SizedBox(width: 8),
                            Text('Loading audio...',
                                style: GoogleFonts.poppins(
                                    fontSize: 12, color: AppTheme.textGrey)),
                          ],
                        ),
                      ),

                    // Seek bar
                    SliderTheme(
                      data: SliderTheme.of(context).copyWith(
                        activeTrackColor: AppTheme.primaryBlue,
                        inactiveTrackColor: Colors.grey.shade300,
                        thumbColor: AppTheme.primaryBlue,
                        thumbShape: const RoundSliderThumbShape(
                            enabledThumbRadius: 8),
                        overlayShape: const RoundSliderOverlayShape(
                            overlayRadius: 14),
                        trackHeight: 3,
                      ),
                      child: Slider(
                          value: _sliderVal,
                          onChanged: _isAudioReady ? _seekTo : null),
                    ),

                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(_fmt(_position), style: GoogleFonts.poppins(
                              fontSize: 11, color: AppTheme.textGrey)),
                          Text(_fmt(_duration), style: GoogleFonts.poppins(
                              fontSize: 11, color: AppTheme.textGrey)),
                        ],
                      ),
                    ),

                    const SizedBox(height: 8),

                    // Controls
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        IconButton(
                          icon: const Icon(Icons.skip_previous_rounded,
                              size: 32),
                          onPressed: () => _player.seek(Duration.zero),
                        ),
                        const SizedBox(width: 12),
                        GestureDetector(
                          onTap: _togglePlay,
                          child: Container(
                            width: 56, height: 56,
                            decoration: BoxDecoration(
                              color: _isAudioReady
                                  ? AppTheme.primaryBlue
                                  : AppTheme.lightBlue.withOpacity(0.5),
                              shape: BoxShape.circle,
                              boxShadow: [BoxShadow(
                                  color: AppTheme.primaryBlue.withOpacity(0.3),
                                  blurRadius: 12,
                                  offset: const Offset(0, 4))],
                            ),
                            child: Icon(
                              _isPlaying
                                  ? Icons.pause_rounded
                                  : Icons.play_arrow_rounded,
                              color: Colors.white, size: 32,
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        IconButton(
                          icon: const Icon(Icons.skip_next_rounded, size: 32),
                          onPressed: () => _player.seek(_duration),
                        ),
                      ],
                    ),
                  ]).animate().fadeIn(delay: 300.ms),

                  const SizedBox(height: 30),
                ],
              ),
            ),

            // ── Download notification banner ───────────────────────────
            if (_showDlNotif)
              Positioned(
                top: 10, left: 16, right: 16,
                child: Material(
                  elevation: 6,
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 12),
                    decoration: BoxDecoration(
                        color: AppTheme.successGreen,
                        borderRadius: BorderRadius.circular(12)),
                    child: Row(children: [
                      const Icon(Icons.download_done_rounded,
                          color: Colors.white, size: 20),
                      const SizedBox(width: 10),
                      Expanded(child: Text('Audio saved to your device!',
                          style: GoogleFonts.poppins(color: Colors.white,
                              fontSize: 13, fontWeight: FontWeight.w500))),
                    ]),
                  ),
                ).animate().fadeIn(duration: 300.ms).slideY(begin: -0.5),
              ),
          ],
        ),
      ),
    );
  }

  // First sentence highlighted in blue, rest in dark
  Widget _highlightedText(String text) {
    if (text.isEmpty) {
      return Text('No translated text received.',
          style: GoogleFonts.poppins(fontSize: 13, color: AppTheme.textGrey));
    }
    final idx = text.indexOf('. ');
    final first = idx != -1 ? text.substring(0, idx + 2) : text;
    final rest  = idx != -1 ? text.substring(idx + 2) : '';
    return RichText(
      text: TextSpan(children: [
        TextSpan(text: first,
            style: GoogleFonts.poppins(color: AppTheme.primaryBlue,
                fontSize: 13, fontWeight: FontWeight.w600)),
        if (rest.isNotEmpty)
          TextSpan(text: rest,
              style: GoogleFonts.poppins(
                  color: AppTheme.textDark, fontSize: 13)),
      ]),
    );
  }

  Widget _actionBtn({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
  }) =>
      GestureDetector(
        onTap: onTap,
        child: Column(children: [
          Container(
            width: 52, height: 52,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: AppTheme.textGrey.withOpacity(0.3)),
            ),
            child: Icon(icon, size: 22, color: AppTheme.textDark),
          ),
          const SizedBox(height: 6),
          Text(label, style: GoogleFonts.poppins(
              fontSize: 12, color: AppTheme.textGrey)),
        ]),
      );

  Widget _circleIcon(IconData icon) => Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          border: Border.all(color: AppTheme.textGrey.withOpacity(0.3)),
          shape: BoxShape.circle,
        ),
        child: Icon(icon, size: 18),
      );
 
}