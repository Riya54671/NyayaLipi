import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:google_fonts/google_fonts.dart';
import '../theme/app_theme.dart';
import 'dashboard_screen.dart';

class LandingScreen extends StatelessWidget {
  const LandingScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        fit: StackFit.expand,
        children: [

          // ── Background Image (Hindi characters) ───────────────────────
          Image.asset(
            'assets/images/image2.png',
            fit: BoxFit.cover,
            width: double.infinity,
            height: double.infinity,
          ),

          // ── Slight white overlay ───────────────────────────────────────
          Container(color: Colors.white.withOpacity(0.15)),

          // ── Center Content ─────────────────────────────────────────────
          Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [

                // ── App Name ──────────────────────────────────────────────
                Text(
                  'NyayaLipi',
                  style: GoogleFonts.dmSans(
                    fontSize: 64,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.primaryBlue,
                    letterSpacing: 0.5,
                    shadows: [
                      Shadow(
                        color: AppTheme.primaryBlue.withOpacity(0.25),
                        blurRadius: 16,
                        offset: const Offset(0, 6),
                      ),
                      Shadow(
                        color: Colors.black.withOpacity(0.10),
                        blurRadius: 8,
                        offset: const Offset(0, 3),
                      ),
                    ],
                  ),
                )
                    .animate()
                    .fadeIn(duration: 700.ms)
                    .slideY(begin: -0.2, end: 0),

                const SizedBox(height: 14),

                // ── Tagline ───────────────────────────────────────────────
                Text(
                  'Cutting through legal\njargon, effortlessly',
                  textAlign: TextAlign.center,
                  style: GoogleFonts.dmSans(
                    fontSize: 20,
                    fontWeight: FontWeight.w500,
                    color: AppTheme.textDark,
                    height: 1.55,
                    shadows: [
                      Shadow(
                        color: Colors.black.withOpacity(0.15),
                        blurRadius: 8,
                        offset: const Offset(0, 3),
                      ),
                    ],
                  ),
                )
                    .animate()
                    .fadeIn(delay: 200.ms, duration: 600.ms),

                const SizedBox(height: 52),

                // ── Let's Translate Button ────────────────────────────────
                ElevatedButton(
                  onPressed: () {
                    Navigator.pushReplacement(
                      context,
                      MaterialPageRoute(
                        builder: (_) => const DashboardScreen(),
                      ),
                    );
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppTheme.primaryBlue,
                    foregroundColor: AppTheme.white,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(30),
                    ),
                    padding: const EdgeInsets.symmetric(
                        horizontal: 48, vertical: 18),
                    elevation: 6,
                    shadowColor: AppTheme.primaryBlue.withOpacity(0.5),
                  ),
                  child: Text(
                    "Let's Translate",
                    style: GoogleFonts.dmSans(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      letterSpacing: 0.3,
                    ),
                  ),
                )
                    .animate()
                    .fadeIn(delay: 400.ms, duration: 600.ms)
                    .slideY(begin: 0.3, end: 0),
              ],
            ),
          ),

          // ── "Landing Page" label — remove before final demo ────────────
          Positioned(
            top: 48,
            left: 16,
            child: Text(
              'Landing Page',
              style: GoogleFonts.dmSans(
                fontSize: 12,
                color: Colors.grey.shade500,
              ),
            ),
          ),
        ],
      ),
    );
  }
}