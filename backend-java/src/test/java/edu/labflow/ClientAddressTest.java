package edu.labflow;

import static org.assertj.core.api.Assertions.*;

import java.util.List;
import org.junit.jupiter.api.Test;

class ClientAddressTest {
  @Test
  void ignoresSpoofedHeaderFromUntrustedPeer() {
    assertThat(ClientAddress.resolve("203.0.113.1", "1.2.3.4", List.of("127.0.0.1/32")))
        .isEqualTo("203.0.113.1");
  }

  @Test
  void selectsNearestUntrustedProxyHop() {
    assertThat(
            ClientAddress.resolve(
                "172.18.0.2", "1.2.3.4, 203.0.113.5, 172.18.0.3", List.of("172.18.0.0/16")))
        .isEqualTo("203.0.113.5");
  }

  @Test
  void malformedOrLongChainFailsClosed() {
    assertThat(ClientAddress.resolve("127.0.0.1", "deadbeef", List.of("127.0.0.1")))
        .isEqualTo("127.0.0.1");
    assertThat(ClientAddress.resolve("127.0.0.1", "attacker.example", List.of("127.0.0.1")))
        .isEqualTo("127.0.0.1");
    assertThat(ClientAddress.resolve("127.0.0.1", "1.2.3.4,".repeat(17), List.of("127.0.0.1")))
        .isEqualTo("127.0.0.1");
  }

  @Test
  void supportsIpv6ProxyNetworks() {
    assertThat(ClientAddress.resolve("::1", "2001:db8::10", List.of("::1/128")))
        .isEqualTo("2001:db8::10");
  }
}
