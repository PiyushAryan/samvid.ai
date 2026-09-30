export type FaviconTheme = "light" | "dark";

export function setFaviconTheme(theme: FaviconTheme) {
  const lightIcon = document.querySelector<HTMLLinkElement>('link[data-samvid-favicon="light"]');
  const darkIcon = document.querySelector<HTMLLinkElement>('link[data-samvid-favicon="dark"]');

  if (lightIcon) lightIcon.media = theme === "light" ? "all" : "not all";
  if (darkIcon) darkIcon.media = theme === "dark" ? "all" : "not all";
}
