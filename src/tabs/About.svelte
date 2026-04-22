<script lang="ts">
  import profileImg from '../assets/about_profile.png';
</script>

<div class="about">
  <img src={profileImg} alt="Trik_Klip" class="profile-img" />

  <div class="social-links">
    <a href="https://twitter.com/trikeri" target="_blank" rel="noopener" title="Twitter/X">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
    </a>
    <a href="https://youtube.com/@trikeri" target="_blank" rel="noopener" title="YouTube">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>
    </a>
    <a href="https://tiktok.com/@trikeri" target="_blank" rel="noopener" title="TikTok">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z"/></svg>
    </a>
    <a href="https://twitch.tv/trikeri" target="_blank" rel="noopener" title="Twitch">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/></svg>
    </a>
    <a href="https://github.com/Trikeri" target="_blank" rel="noopener" title="GitHub">
      <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>
    </a>
  </div>

  <p class="blurb">
    Made by Trikeri, if you pirated this the least you can do is go follow me and increase my reputation bar ya chump.
  </p>
</div>

<style>
  .about {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 6px;
    text-align: center;
  }

  .profile-img {
    width: 160px;
    height: 160px;
    border-radius: 12px;
    object-fit: cover;
    margin-bottom: 8px;
  }

  .app-name {
    font-size: 22px;
    color: var(--accent);
    margin: 0;
    font-weight: 700;
  }

  .tagline {
    color: var(--dim);
    font-size: 14px;
    margin-bottom: 12px;
  }

  .social-links {
    display: flex;
    gap: 16px;
    margin: 8px 0;
  }

  .social-links a {
    display: flex;
    align-items: center;
    color: var(--accent);
    text-decoration: none;
    transition: color 0.15s;
  }

  .social-links a:hover {
    color: #ffffff;
  }

  .social-links svg {
    width: 22px;
    height: 22px;
  }

  .blurb {
    color: var(--dim);
    font-size: 13px;
    line-height: 1.6;
    margin-top: 12px;
  }
</style>
