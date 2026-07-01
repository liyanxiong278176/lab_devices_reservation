package com.lab.reservation.service;

import java.time.LocalDate;

public record SlotKey(Long deviceId, LocalDate date, int slotIndex) {}
