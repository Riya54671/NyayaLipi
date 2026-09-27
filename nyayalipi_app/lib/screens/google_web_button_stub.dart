import 'package:flutter/material.dart';

// Used on non-web platforms (Android/iOS/desktop) so the real
// google_sign_in_web package — which only compiles for Flutter Web — is
// never imported into those builds. Nothing here actually runs: the app
// only calls renderButton() inside an `if (kIsWeb)` branch, but Dart still
// needs these symbols to exist so the file type-checks on every platform.

class GSIButtonConfiguration {
  const GSIButtonConfiguration({
    this.type,
    this.theme,
    this.size,
    this.text,
    this.shape,
    this.logoAlignment,
    this.minimumWidth,
  });
  final GSIButtonType? type;
  final GSIButtonTheme? theme;
  final GSIButtonSize? size;
  final GSIButtonText? text;
  final GSIButtonShape? shape;
  final GSIButtonLogoAlignment? logoAlignment;
  final double? minimumWidth;
}

enum GSIButtonType { standard, icon }
enum GSIButtonTheme { outline, filledBlue, filledBlack }
enum GSIButtonSize { small, medium, large }
enum GSIButtonText { signinWith, signupWith, continueWith, signin }
enum GSIButtonShape { rectangular, pill }
enum GSIButtonLogoAlignment { left, center }

Widget renderButton({GSIButtonConfiguration? configuration}) {
  return const SizedBox.shrink(); // never actually reached on this platform
}