package edu.labflow;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import java.net.InetAddress;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class ClientAddress {
  private final List<String> proxies;

  public ClientAddress(Settings settings) {
    try {
      proxies =
          new ObjectMapper()
              .readValue(settings.get("TRUSTED_PROXY_IPS", "[]"), new TypeReference<>() {});
    } catch (Exception e) {
      throw new IllegalStateException("LAB_TRUSTED_PROXY_IPS must be a JSON list");
    }
  }

  public String ip(HttpServletRequest request) {
    return resolve(request.getRemoteAddr(), request.getHeader("X-Forwarded-For"), proxies);
  }

  private static byte[] address(String value) throws Exception {
    if (!value.matches("[0-9]+(?:\\.[0-9]+){3}")
        && !(value.contains(":") && value.matches("[0-9a-fA-F:.]+")))
      throw new IllegalArgumentException("Invalid IP");
    return InetAddress.getByName(value).getAddress();
  }

  private static boolean trusted(byte[] ip, List<String> proxies) throws Exception {
    for (String cidr : proxies) {
      String[] parts = cidr.split("/", -1);
      byte[] network = address(parts[0]);
      int bits = parts.length == 1 ? network.length * 8 : Integer.parseInt(parts[1]);
      if (parts.length > 2 || bits < 0 || bits > network.length * 8)
        throw new IllegalArgumentException("Invalid network");
      if (ip.length != network.length) continue;
      boolean same = true;
      for (int bit = 0; bit < bits; bit++)
        if ((ip[bit / 8] & (1 << (7 - bit % 8))) != (network[bit / 8] & (1 << (7 - bit % 8)))) {
          same = false;
          break;
        }
      if (same) return true;
    }
    return false;
  }

  static String resolve(String peer, String forwarded, List<String> proxies) {
    if (peer == null) return "unknown";
    try {
      byte[] direct = address(peer);
      if (forwarded == null || forwarded.length() > 1024 || !trusted(direct, proxies)) return peer;
      String[] chain = forwarded.split(",", -1);
      if (chain.length > 16) return peer;
      var addresses = new ArrayList<byte[]>();
      for (String value : chain) addresses.add(address(value.strip()));
      for (int i = addresses.size() - 1; i >= 0; i--)
        if (!trusted(addresses.get(i), proxies)) return chain[i].strip();
      return chain[0].strip();
    } catch (Exception e) {
      return peer;
    }
  }
}
