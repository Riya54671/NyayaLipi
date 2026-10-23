import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../screens/profile_screen.dart';

class ProfileButton extends StatelessWidget {
  final VoidCallback? onReturn; // called after the profile screen closes
  const ProfileButton({super.key, this.onReturn});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () async {
        await Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const ProfileScreen()),
        );
        onReturn?.call();
      },
      child: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          border: Border.all(color: AppTheme.textGrey.withValues(alpha: 0.3)),
          shape: BoxShape.circle,
        ),
        child: const Icon(Icons.person_outline, size: 24, color: AppTheme.textDark),
      ),
    );
  }
}