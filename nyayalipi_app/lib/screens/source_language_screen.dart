import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'dart:io';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../theme/app_theme.dart';
import 'voice_output_screen.dart';

class SourceLanguageScreen extends StatefulWidget {
  final String fileName;
  final File? pickedFile;
  final String backendBaseUrl;
  final Map<String, String> langCode;

  const SourceLanguageScreen({
    super.key,
    required this.fileName,
    required this.pickedFile,
    required this.backendBaseUrl,
    required this.langCode,
  });

  @override
  State<SourceLanguageScreen> createState() => _SourceLanguageScreenState();
}

class _SourceLanguageScreenState extends State<SourceLanguageScreen> {
  String? _sourceLanguage;
  String? _targetLanguage;
  bool _isLoading = false;
  String _statusMessage = '';

  final List<String> _languages = [
    'Hindi', 'Marathi', 'Tamil', 'Telugu',
    'English', 'Kannada', 'Bengali', 'Gujarati', 'Punjabi',
  ];

  Future<void> _handleSubmit() async {
    if (_sourceLanguage == null || _targetLanguage == null) return;
    setState(() { _isLoading = true; _statusMessage = 'Translating document...'; });

    String translatedText = '';
    String audioBase64    = '';
    String docUrl         = '';

    try {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('${widget.backendBaseUrl}/translate'),
      );
      request.fields['source_language'] =
          widget.langCode[_sourceLanguage] ?? 'ta-IN';
      request.fields['target_language'] =
          widget.langCode[_targetLanguage!] ?? 'hi-IN';
      if (widget.pickedFile != null) {
        request.files.add(
          await http.MultipartFile.fromPath('file', widget.pickedFile!.path),
        );
      }
      setState(() => _statusMessage = 'Generating voice output...');
      final streamedResponse = await request.send()
          .timeout(const Duration(seconds: 15));
      final responseBody = await streamedResponse.stream.bytesToString();

      if (streamedResponse.statusCode == 200) {
        final data     = jsonDecode(responseBody);
        translatedText = data['translated_text'] ?? '';
        audioBase64    = data['audio_base64']    ?? '';
        docUrl         = data['doc_url']         ?? '';
      } else {
        throw Exception('Non-200 status');
      }
    } catch (_) {
      translatedText =
          'India has one of the most linguistically diverse populations in the world, '
          'with over 500 languages spoken across the country, 22 of which are officially '
          'recognised by the 8th Schedule of the Constitution. This diversity, while '
          'culturally rich, creates significant barriers in critical domains such as '
          'law and governance.';
      audioBase64 = '';
    }

    if (mounted) {
      setState(() { _isLoading = false; _statusMessage = ''; });
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (_) => VoiceOutputScreen(
            sourceLanguage: _sourceLanguage!,
            targetLanguage: _targetLanguage!,
            translatedText: translatedText,
            audioBase64:    audioBase64,
            docUrl:         docUrl,
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.white,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [

              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Column(crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Welcome user!',
                          style: GoogleFonts.poppins(fontSize: 26,
                              fontWeight: FontWeight.w800,
                              color: AppTheme.primaryBlue)),
                      Text('Lets translate your documents.',
                          style: GoogleFonts.poppins(
                              fontSize: 13, color: AppTheme.textGrey)),
                    ],
                  ),
                  _profileIcon(),
                ],
              ).animate().fadeIn(duration: 400.ms),

              const SizedBox(height: 16),

              Row(children: [
                _circleIcon(Icons.upload_rounded),
                const SizedBox(width: 10),
                Column(crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Upload Document',
                        style: GoogleFonts.poppins(
                            fontWeight: FontWeight.w600, fontSize: 15)),
                    Text('Select and upload document of your choice',
                        style: GoogleFonts.poppins(
                            fontSize: 11, color: AppTheme.textGrey)),
                  ],
                ),
              ]).animate().fadeIn(delay: 100.ms),

              const Divider(height: 20),

              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                    color: AppTheme.backgroundBlue,
                    borderRadius: BorderRadius.circular(16)),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 24),
                  decoration: BoxDecoration(
                    border: Border.all(
                        color: AppTheme.primaryBlue.withOpacity(0.4),
                        width: 1.5),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(children: [
                    const Icon(Icons.upload_outlined,
                        size: 36, color: AppTheme.textDark),
                    const SizedBox(height: 12),
                    Row(mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 16, vertical: 10),
                          decoration: BoxDecoration(
                              color: AppTheme.textDark,
                              borderRadius: BorderRadius.circular(8)),
                          child: Text(
                            widget.fileName.isNotEmpty
                                ? widget.fileName : 'doc_name.png',
                            style: GoogleFonts.poppins(
                                color: AppTheme.white, fontSize: 13),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(
                              color: Colors.grey.shade300,
                              borderRadius: BorderRadius.circular(6)),
                          child: const Icon(Icons.delete_outline,
                              size: 18, color: Colors.black54),
                        ),
                      ],
                    ),
                  ]),
                ),
              ).animate().fadeIn(delay: 150.ms),

              const SizedBox(height: 20),

              Container(
                decoration: BoxDecoration(
                  border: Border.all(
                      color: AppTheme.primaryBlue.withOpacity(0.3)),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(children: [
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Text('Detected Language',
                        style: GoogleFonts.poppins(
                            fontWeight: FontWeight.w600, fontSize: 15)),
                  ),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    color: AppTheme.primaryBlue,
                    child: Text('Tamil', textAlign: TextAlign.center,
                        style: GoogleFonts.poppins(color: AppTheme.white,
                            fontWeight: FontWeight.w600, fontSize: 15)),
                  ),
                  Row(children: [
                    Expanded(
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        decoration: const BoxDecoration(
                          color: AppTheme.primaryBlue,
                          borderRadius: BorderRadius.only(
                              bottomLeft: Radius.circular(11)),
                        ),
                        child: Text('YES', textAlign: TextAlign.center,
                            style: GoogleFonts.poppins(color: AppTheme.white,
                                fontWeight: FontWeight.w700)),
                      ),
                    ),
                    Container(width: 1, color: AppTheme.white),
                    Expanded(
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        decoration: const BoxDecoration(
                          color: AppTheme.darkBlue,
                          borderRadius: BorderRadius.only(
                              bottomRight: Radius.circular(11)),
                        ),
                        child: Text('NO', textAlign: TextAlign.center,
                            style: GoogleFonts.poppins(color: AppTheme.white,
                                fontWeight: FontWeight.w700)),
                      ),
                    ),
                  ]),
                ]),
              ).animate().fadeIn(delay: 200.ms),

              const SizedBox(height: 16),

              _buildDropdown(
                hint: 'Enter Source Language',
                value: _sourceLanguage,
                onChanged: (val) => setState(() => _sourceLanguage = val),
              ).animate().fadeIn(delay: 250.ms),

              const SizedBox(height: 14),

              _buildDropdown(
                hint: 'Target Language',
                value: _targetLanguage,
                onChanged: (val) => setState(() => _targetLanguage = val),
              ).animate().fadeIn(delay: 300.ms),

              const SizedBox(height: 24),

              if (_isLoading && _statusMessage.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Row(children: [
                    const SizedBox(width: 16, height: 16,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: AppTheme.primaryBlue)),
                    const SizedBox(width: 10),
                    Text(_statusMessage,
                        style: GoogleFonts.poppins(
                            fontSize: 13, color: AppTheme.textGrey)),
                  ]),
                ),

              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: (_sourceLanguage != null &&
                          _targetLanguage != null && !_isLoading)
                      ? _handleSubmit : null,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.primaryBlue,
                    disabledBackgroundColor:
                        AppTheme.lightBlue.withOpacity(0.4),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12)),
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  child: _isLoading
                      ? const SizedBox(height: 20, width: 20,
                          child: CircularProgressIndicator(
                              color: Colors.white, strokeWidth: 2))
                      : Text('Submit',
                          style: GoogleFonts.poppins(
                              fontWeight: FontWeight.w700,
                              fontSize: 16, color: AppTheme.white)),
                ),
              ).animate().fadeIn(delay: 350.ms),

              const SizedBox(height: 30),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDropdown({
    required String hint,
    required String? value,
    required void Function(String?) onChanged,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        border: Border.all(color: AppTheme.primaryBlue.withOpacity(0.4)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          isExpanded: true,
          hint: Text(hint, style: GoogleFonts.poppins(
              fontSize: 14, color: AppTheme.textGrey)),
          value: value,
          items: _languages.map((lang) => DropdownMenuItem(
                value: lang,
                child: Text(lang, style: GoogleFonts.poppins(fontSize: 14)),
              )).toList(),
          onChanged: onChanged,
          icon: const Icon(Icons.keyboard_arrow_down,
              color: AppTheme.primaryBlue),
        ),
      ),
    );
  }

  Widget _circleIcon(IconData icon) => Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          border: Border.all(color: AppTheme.textGrey.withOpacity(0.3)),
          shape: BoxShape.circle,
        ),
        child: Icon(icon, size: 18),
      );

  Widget _profileIcon() => Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          border: Border.all(color: AppTheme.textGrey.withOpacity(0.3)),
          shape: BoxShape.circle,
        ),
        child: const Icon(Icons.person_outline, size: 24),
      );
}