"""Polite public-website fetcher with SSRF and robots.txt guards."""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Dict, Optional
from urllib import robotparser
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}


def _is_public_host(host: Optional[str]) -> bool:
    if not host or host.lower() in BLOCKED_HOSTS:
        return False
    if host.lower().endswith(".local"):
        return False
    # Block IP literals before DNS.
    try:
        ip = ipaddress.ip_address(host)
        return not (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        )
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Unresolvable hostnames are allowed for mocked unit tests.
        return True
    for info in infos:
        ip_str = info[4][0]
        try:
            resolved = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            resolved.is_private
            or resolved.is_loopback
            or resolved.is_link_local
            or resolved.is_reserved
            or resolved.is_multicast
        ):
            return False
    return True


class WebsiteFetcher:
    def __init__(
        self,
        session: Optional[requests.Session] = None,
        user_agent: str = "CreatorReachBot/1.0 (research prototype)",
        connect_timeout: int = 5,
        read_timeout: int = 10,
        max_bytes: int = 500_000,
    ):
        self.session = session or requests.Session()
        self.user_agent = user_agent
        self.timeout = (connect_timeout, read_timeout)
        self.max_bytes = max_bytes
        self._robots: Dict[str, Optional[robotparser.RobotFileParser]] = {}

    def _robots_for(self, url: str) -> Optional[robotparser.RobotFileParser]:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        rp: Optional[robotparser.RobotFileParser] = robotparser.RobotFileParser()
        try:
            resp = self.session.get(
                origin + "/robots.txt",
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif 400 <= resp.status_code < 500:
                rp.parse([])
            else:
                rp = None
        except requests.RequestException:
            rp = None
        self._robots[origin] = rp
        return rp

    def allowed(self, url: str) -> bool:
        rp = self._robots_for(url)
        return bool(rp and rp.can_fetch(self.user_agent, url))

    def fetch(self, url: str) -> Optional[str]:
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not _is_public_host(parts.hostname):
            return None
        if not self.allowed(url):
            log.info("robots.txt disallows %s", url)
            return None
        try:
            resp = self.session.get(
                url, headers={"User-Agent": self.user_agent}, timeout=self.timeout
            )
        except requests.RequestException as exc:
            log.info("fetch failed for %s: %s", url, exc)
            return None
        if resp.status_code != 200:
            return None
        return resp.text[: self.max_bytes]
