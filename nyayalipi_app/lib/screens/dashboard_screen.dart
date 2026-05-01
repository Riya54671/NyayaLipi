import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:file_picker/file_picker.dart';
import 'dart:io';
import 'dart:convert';
import '../theme/app_theme.dart';
import 'source_language_screen.dart';
import 'voice_output_screen.dart';
import '../services/api_service.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  String? _fileName;
  File? _pickedFile;

  String _detectedLanguage = 'Detecting...';

  bool? _languageConfirmed;
  String? _targetLanguage;
  bool _isLoading = false;
  bool _showNotification = false;
  String _notificationMessage = '';
  bool _notificationIsError = false;
  Uint8List? _fileBytes; // add this with other state variables

  static const String _backendBaseUrl = 'http://10.92.168.64:8000';
  
  

  final List<String> _languages = [
    'Hindi', 'Marathi', 'Tamil', 'Telugu',
    'English', 'Kannada', 'Bengali', 'Gujarati', 'Punjabi',
  ];

  final Map<String, String> _langCode = {
    'Hindi': 'hi-IN',   'Marathi': 'mr-IN', 'Tamil': 'ta-IN',
    'Telugu': 'te-IN',  'English': 'en-IN',  'Kannada': 'kn-IN',
    'Bengali': 'bn-IN', 'Gujarati': 'gu-IN', 'Punjabi': 'pa-IN',
  };
  Future<void> _detectLanguage() async {
  if (_pickedFile == null) {
    print('[DEBUG] _pickedFile is null, skipping detect');
    return;
  }
  print('[DEBUG] Starting detect, file: ${_pickedFile!.path}');
  print('[DEBUG] File exists: ${await _pickedFile!.exists()}');
  setState(() => _detectedLanguage = 'Detecting...');
  try {
    print('[DEBUG] Calling ApiService.detectLanguage...');
    final detected = await ApiService.detectLanguage(_pickedFile!);
    print('[DEBUG] Detected: $detected');
    setState(() => _detectedLanguage = detected);
  } catch (e, stack) {
    print('[DEBUG] Detection error: $e');
    print('[DEBUG] Stack: $stack');
    _showBanner('Detection failed: $e', isError: true);
    setState(() => _detectedLanguage = 'Unknown');
  }
}

  Future<void> _pickFile() async {
  try {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf', 'png', 'jpg', 'jpeg', 'docx'],
      withData: true,  // ← CHANGE false TO true (needed for web)
    );

    if (result != null) {
      final pickedFile = result.files.single;

      setState(() {
        _fileName   = pickedFile.name;
        _pickedFile = pickedFile.path != null ? File(pickedFile.path!) : null;
        _fileBytes  = pickedFile.bytes; // ← store raw bytes for web
        _languageConfirmed = null;
        _targetLanguage    = null;
      });

      _showBanner('Document uploaded: ${pickedFile.name}');
      await _detectLanguage();
    }
  } catch (e) {
    _showBanner('Could not pick file: $e', isError: true);
  }
}

  void _removeFile() => setState(() {
        _fileName          = null;
        _pickedFile        = null;
        _languageConfirmed = null;
        _targetLanguage    = null;
      });

  void _handleYes() {
    setState(() => _languageConfirmed = true);
  }

  void _handleNo() {
  setState(() => _languageConfirmed = false);

  Navigator.push(
    context,
    MaterialPageRoute(
      builder: (_) => SourceLanguageScreen(
        fileName: _fileName ?? 'demo_document.pdf',
        pickedFile: _pickedFile,
        backendBaseUrl: _backendBaseUrl,
        langCode: _langCode,
      ),
    ),
  );
}
  Future<void> _handleSubmit() async {
  if (_targetLanguage == null) return;
  if (_pickedFile == null) {               // ← ADD guard
    _showBanner('File not available', isError: true);
    return;
  }
  setState(() => _isLoading = true);
  try {
    final result = await ApiService.translateDocument(
      file: _pickedFile!,                  // ← clean, no bytes
      sourceLanguage: _detectedLanguage,
      targetLanguage: _targetLanguage!,
      generateAudio: true,
    );
    if (mounted) {
      setState(() => _isLoading = false);
      print('[DEBUG] docUrl: ${ApiService.BASE_URL}${result['document_download_url'] ?? ''}');
      print('[DEBUG] audioUrl: ${result['audio_download_url']}');
      Navigator.push(
  context,
  MaterialPageRoute(
    builder: (_) => VoiceOutputScreen(
      sourceLanguage: _detectedLanguage,
      targetLanguage: _targetLanguage!,
      translatedText: result['translated_text_preview'] ?? '',
      audioBase64: result['audio_download_url'] != null
          ? '${ApiService.BASE_URL}${result['audio_download_url']}'
          : '',
      docUrl: '${ApiService.BASE_URL}${result['document_download_url'] ?? ''}',
    ),
  ),
);
    }
  } catch (e) {
    setState(() => _isLoading = false);
    _showBanner('Error: $e', isError: true);
  }
}
  void _showBanner(String msg, {bool isError = false}) {
    setState(() {
      _notificationMessage = msg;
      _notificationIsError = isError;
      _showNotification    = true;
    });
    Future.delayed(const Duration(seconds: 3), () {
      if (mounted) setState(() => _showNotification = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final bool submitEnabled = _languageConfirmed == true &&
        _targetLanguage != null &&
        !_isLoading;

    return Scaffold(
      backgroundColor: AppTheme.white,
      body: SafeArea(
        child: Stack(
          children: [
            SingleChildScrollView(
              padding:
                  const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [

                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Welcome user!',
                              style: GoogleFonts.poppins(
                                  fontSize: 26,
                                  fontWeight: FontWeight.w800,
                                  color: AppTheme.primaryBlue)),
                          Text('Lets translate your documents.',
                              style: GoogleFonts.poppins(
                                  fontSize: 13,
                                  color: AppTheme.textGrey)),
                        ],
                      ),
                      
                    ],
                  ).animate().fadeIn(duration: 500.ms),

                  const SizedBox(height: 16),

                  Row(
                    children: [
                      _circleIcon(Icons.upload_rounded),
                      const SizedBox(width: 10),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Upload Document',
                              style: GoogleFonts.poppins(
                                  fontWeight: FontWeight.w600,
                                  fontSize: 15)),
                          Text(
                              'Select and upload document of your choice',
                              style: GoogleFonts.poppins(
                                  fontSize: 11,
                                  color: AppTheme.textGrey)),
                        ],
                      ),
                    ],
                  ).animate().fadeIn(delay: 100.ms),

                  const Divider(height: 20),

                  GestureDetector(
                    onTap: _pickFile,
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                          color: AppTheme.backgroundBlue,
                          borderRadius: BorderRadius.circular(16)),
                      child: Container(
                        padding:
                            const EdgeInsets.symmetric(vertical: 24),
                        decoration: BoxDecoration(
                          border: Border.all(
                              color: AppTheme.primaryBlue
                                  .withOpacity(0.4),
                              width: 1.5),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Column(
                          children: [
                            const Icon(Icons.upload_outlined,
                                size: 36, color: AppTheme.textDark),
                            const SizedBox(height: 12),
                            Row(
                              mainAxisAlignment:
                                  MainAxisAlignment.center,
                              children: [
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 16, vertical: 10),
                                  decoration: BoxDecoration(
                                      color: AppTheme.textDark,
                                      borderRadius:
                                          BorderRadius.circular(8)),
                                  child: Text(
                                    _fileName ?? 'Upload Document',
                                    style: GoogleFonts.poppins(
                                        color: AppTheme.white,
                                        fontSize: 13,
                                        fontWeight: FontWeight.w500),
                                  ),
                                ),
                                if (_fileName != null) ...[
                                  const SizedBox(width: 8),
                                  GestureDetector(
                                    onTap: _removeFile,
                                    child: Container(
                                      padding: const EdgeInsets.all(8),
                                      decoration: BoxDecoration(
                                          color: Colors.grey.shade300,
                                          borderRadius:
                                              BorderRadius.circular(
                                                  6)),
                                      child: const Icon(
                                          Icons.delete_outline,
                                          size: 18,
                                          color: Colors.black54),
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          ],
                        ),
                      ),
                    ),
                  ).animate().fadeIn(delay: 150.ms),

                  const SizedBox(height: 20),

                  Container(
                    decoration: BoxDecoration(
                      border: Border.all(
                          color: AppTheme.primaryBlue.withOpacity(0.3)),
                      borderRadius: BorderRadius.circular(12),
                      color: AppTheme.white,
                    ),
                    child: Column(
                      children: [
                        Padding(
                          padding:
                              const EdgeInsets.symmetric(vertical: 12),
                          child: Text('Detected Language',
                              style: GoogleFonts.poppins(
                                  fontWeight: FontWeight.w600,
                                  fontSize: 15)),
                        ),
                        Container(
                          width: double.infinity,
                          padding:
                              const EdgeInsets.symmetric(vertical: 12),
                          decoration: const BoxDecoration(
                              color: AppTheme.primaryBlue),
                          child: Text(
                            _detectedLanguage,
                            textAlign: TextAlign.center,
                            style: GoogleFonts.poppins(
                                color: AppTheme.white,
                                fontWeight: FontWeight.w600,
                                fontSize: 15),
                          ),
                        ),
                        Row(
                          children: [
                            Expanded(
                              child: GestureDetector(
                                onTap: _handleYes,
                                child: Container(
                                  padding: const EdgeInsets.symmetric(
                                      vertical: 12),
                                  decoration: BoxDecoration(
                                    color: _languageConfirmed == true
                                        ? AppTheme.darkBlue
                                        : AppTheme.primaryBlue,
                                    borderRadius:
                                        const BorderRadius.only(
                                            bottomLeft:
                                                Radius.circular(11)),
                                  ),
                                  child: Text('YES',
                                      textAlign: TextAlign.center,
                                      style: GoogleFonts.poppins(
                                          color: AppTheme.white,
                                          fontWeight: FontWeight.w700,
                                          fontSize: 14)),
                                ),
                              ),
                            ),
                            Container(
                                width: 1, color: AppTheme.white),
                            Expanded(
                              child: GestureDetector(
                                onTap: _handleNo,
                                child: Container(
                                  padding: const EdgeInsets.symmetric(
                                      vertical: 12),
                                  decoration: BoxDecoration(
                                    color: _languageConfirmed == false
                                        ? AppTheme.darkBlue
                                        : AppTheme.primaryBlue,
                                    borderRadius:
                                        const BorderRadius.only(
                                            bottomRight:
                                                Radius.circular(11)),
                                  ),
                                  child: Text('NO',
                                      textAlign: TextAlign.center,
                                      style: GoogleFonts.poppins(
                                          color: AppTheme.white,
                                          fontWeight: FontWeight.w700,
                                          fontSize: 14)),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ).animate().fadeIn(delay: 200.ms),

                  const SizedBox(height: 16),

                  if (_languageConfirmed == true) ...[
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 14),
                      decoration: BoxDecoration(
                        border: Border.all(
                            color:
                                AppTheme.primaryBlue.withOpacity(0.4)),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(_detectedLanguage,
                          style: GoogleFonts.poppins(
                              fontSize: 14,
                              color: AppTheme.textDark)),
                    ).animate().fadeIn(duration: 300.ms),
                    const SizedBox(height: 12),
                  ],

                  _buildDropdown(
                    hint: 'Target Language',
                    value: _targetLanguage,
                    onChanged: (val) =>
                        setState(() => _targetLanguage = val),
                  ).animate().fadeIn(delay: 250.ms),

                  const SizedBox(height: 8),

                  if (_languageConfirmed == null)
                    Padding(
                      padding: const EdgeInsets.only(top: 4, left: 4),
                      child: Text(
                        'Tap YES or NO above to continue',
                        style: GoogleFonts.poppins(
                            fontSize: 12,
                            color: AppTheme.textGrey
                                .withOpacity(0.7)),
                      ),
                    ),

                  if (_languageConfirmed == true &&
                      _targetLanguage == null)
                    Padding(
                      padding: const EdgeInsets.only(top: 4, left: 4),
                      child: Text(
                        'Select a target language to enable Submit',
                        style: GoogleFonts.poppins(
                            fontSize: 12,
                            color: AppTheme.textGrey
                                .withOpacity(0.7)),
                      ),
                    ),

                  const SizedBox(height: 16),

                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: submitEnabled ? _handleSubmit : null,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppTheme.primaryBlue,
                        disabledBackgroundColor:
                            AppTheme.lightBlue.withOpacity(0.4),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12)),
                        padding:
                            const EdgeInsets.symmetric(vertical: 16),
                      ),
                      child: _isLoading
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(
                                  color: Colors.white,
                                  strokeWidth: 2))
                          : Text('Submit',
                              style: GoogleFonts.poppins(
                                  fontWeight: FontWeight.w700,
                                  fontSize: 16,
                                  color: AppTheme.white)),
                    ),
                  ).animate().fadeIn(delay: 300.ms),

                  const SizedBox(height: 30),
                ],
              ),
            ),

            if (_showNotification)
              Positioned(
                top: 10,
                left: 16,
                right: 16,
                child: Material(
                  elevation: 6,
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 12),
                    decoration: BoxDecoration(
                      color: _notificationIsError
                          ? Colors.redAccent
                          : AppTheme.successGreen,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      children: [
                        Icon(
                          _notificationIsError
                              ? Icons.error_outline
                              : Icons.check_circle,
                          color: Colors.white,
                          size: 20,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(_notificationMessage,
                              style: GoogleFonts.poppins(
                                  color: Colors.white,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w500)),
                        ),
                      ],
                    ),
                  ),
                )
                    .animate()
                    .fadeIn(duration: 300.ms)
                    .slideY(begin: -0.5),
              ),
          ],
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
        border:
            Border.all(color: AppTheme.primaryBlue.withOpacity(0.4)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          isExpanded: true,
          hint: Text(hint,
              style: GoogleFonts.poppins(
                  fontSize: 14, color: AppTheme.textGrey)),
          value: value,
          items: _languages
              .map((lang) => DropdownMenuItem(
                    value: lang,
                    child: Text(lang,
                        style: GoogleFonts.poppins(fontSize: 14)),
                  ))
              .toList(),
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
          border: Border.all(
              color: AppTheme.textGrey.withOpacity(0.3)),
          shape: BoxShape.circle,
        ),
        child: Icon(icon, size: 18),
      );

  
}