package com.lab.reservation.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.ReservationItemMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.impl.ReservationServiceImpl;
import com.lab.reservation.vo.reservation.ReservationVO;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * 预约生命周期状态机 TDD 测试（mock mapper，纯单测，不起 Spring 容器）。
 *
 * 覆盖规格 §6.3 状态机的关键转换：
 * <pre>
 * PENDING/APPROVED --cancel(start前)--> CANCELLED
 * APPROVED --checkIn(在时间窗)--> IN_USE  (device -> IN_USE)
 * IN_USE  --checkOut--> COMPLETED          (device -> IDLE)
 * APPROVED/IN_USE --markViolated--> VIOLATED (device IN_USE -> IDLE)
 * APPROVED --markNoShow--> NO_SHOW         (device IN_USE -> IDLE)
 * </pre>
 * 每个转换断言：status 写入 + 设备状态联动 + reservation_item 释放（itemMapper.delete called）。
 */
@ExtendWith(MockitoExtension.class)
class ReservationLifecycleTest {

    @Mock private DeviceMapper deviceMapper;
    @Mock private ReservationMapper reservationMapper;
    @Mock private ReservationItemMapper itemMapper;
    @Mock private SlotCalculatorService slotCalculator;
    @Mock private NotificationService notificationService;

    @InjectMocks
    private ReservationServiceImpl service;

    private static final long RES_ID = 100L;
    private static final long DEVICE_ID = 7L;
    private static final long OWNER_ID = 1L;
    private static final long OTHER_ID = 2L;

    @BeforeEach
    void setUp() {
        // @Value("${lab.slot.check-in-grace-minutes:0}") 注入：模拟 Spring 装配，赋默认 0。
        ReflectionTestUtils.setField(service, "graceMinutes", 0L);
    }

    // ---------- 工具 ----------

    private Reservation reservation(ReservationStatus status, long userId, LocalDateTime start, LocalDateTime end) {
        Reservation r = new Reservation();
        r.setId(RES_ID);
        r.setUserId(userId);
        r.setDeviceId(DEVICE_ID);
        r.setStatus(status.name());
        r.setStartTime(start);
        r.setEndTime(end);
        return r;
    }

    private Device device(String status) {
        Device d = new Device();
        d.setId(DEVICE_ID);
        d.setStatus(status);
        return d;
    }

    /** 构造 SecurityUserDetails mock：本人（userId 匹配），无 device:approve 权限。 */
    private SecurityUserDetails ownerUd(long userId) {
        SecurityUserDetails ud = mock(SecurityUserDetails.class);
        when(ud.getUserId()).thenReturn(userId);
        when(ud.getAuthorities()).thenReturn(java.util.List.<GrantedAuthority>of());
        return ud;
    }

    /** 构造 SecurityUserDetails mock：非本人，权限集合自定义。 */
    private SecurityUserDetails udWithAuthorities(long userId, GrantedAuthority... auths) {
        SecurityUserDetails ud = mock(SecurityUserDetails.class);
        when(ud.getUserId()).thenReturn(userId);
        when(ud.getAuthorities()).thenReturn(java.util.List.of(auths));
        return ud;
    }

    // ---------- cancel ----------

    @Test
    void cancel_pending_before_start_succeeds() {
        LocalDateTime start = LocalDateTime.now().plusHours(2);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.PENDING, OWNER_ID, start, end);
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        service.cancel(RES_ID, OWNER_ID);

        ArgumentCaptor<Reservation> captor = ArgumentCaptor.forClass(Reservation.class);
        verify(reservationMapper).updateById(captor.capture());
        assertEquals(ReservationStatus.CANCELLED.name(), captor.getValue().getStatus());
        verify(itemMapper).delete(any());
    }

    @Test
    void cancel_in_use_rejected() {
        LocalDateTime start = LocalDateTime.now().minusMinutes(10);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.IN_USE, OWNER_ID, start, end);
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.cancel(RES_ID, OWNER_ID));
        assertEquals(ResultCode.STATUS_TRANSITION_INVALID.getCode(), e.getCode());
        verify(itemMapper, never()).delete(any());
    }

    @Test
    void cancel_by_non_owner_rejected() {
        LocalDateTime start = LocalDateTime.now().plusHours(2);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.PENDING, OWNER_ID, start, end);
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.cancel(RES_ID, OTHER_ID));
        assertEquals(ResultCode.FORBIDDEN.getCode(), e.getCode());
    }

    @Test
    void cancel_after_start_rejected() {
        // APPROVED 但已过 startTime：状态转换非法（不能取消已开始的预约）
        LocalDateTime start = LocalDateTime.now().minusHours(1);
        LocalDateTime end = start.plusHours(2);
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID, start, end);
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.cancel(RES_ID, OWNER_ID));
        assertEquals(ResultCode.STATUS_TRANSITION_INVALID.getCode(), e.getCode());
    }

    // ---------- checkIn ----------

    @Test
    void checkIn_approved_in_window_succeeds() {
        LocalDateTime start = LocalDateTime.now().minusMinutes(5);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID, start, end);
        Device d = device("IDLE");
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);
        when(deviceMapper.selectById(DEVICE_ID)).thenReturn(d);

        service.checkIn(RES_ID, ownerUd(OWNER_ID));

        ArgumentCaptor<Reservation> rc = ArgumentCaptor.forClass(Reservation.class);
        verify(reservationMapper).updateById(rc.capture());
        assertEquals(ReservationStatus.IN_USE.name(), rc.getValue().getStatus());
        assertNotNull(rc.getValue().getCheckInAt());

        ArgumentCaptor<Device> dc = ArgumentCaptor.forClass(Device.class);
        verify(deviceMapper).updateById(dc.capture());
        assertEquals("IN_USE", dc.getValue().getStatus());
    }

    @Test
    void checkIn_before_start_minus_grace_rejected() {
        LocalDateTime start = LocalDateTime.now().plusMinutes(30);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID, start, end);
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.checkIn(RES_ID, ownerUd(OWNER_ID)));
        assertEquals(ResultCode.STATUS_TRANSITION_INVALID.getCode(), e.getCode());
    }

    @Test
    void checkIn_pending_rejected() {
        LocalDateTime start = LocalDateTime.now().minusMinutes(5);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.PENDING, OWNER_ID, start, end);
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.checkIn(RES_ID, ownerUd(OWNER_ID)));
        assertEquals(ResultCode.STATUS_TRANSITION_INVALID.getCode(), e.getCode());
    }

    @Test
    void checkIn_notOwner_noApprover_forbidden() {
        LocalDateTime start = LocalDateTime.now().minusMinutes(5);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID, start, end);
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.checkIn(RES_ID, ownerUd(OTHER_ID)));
        assertEquals(ResultCode.FORBIDDEN.getCode(), e.getCode());
        verify(reservationMapper, never()).updateById(any());
    }

    @Test
    void checkOut_notOwner_butApprover_ok() {
        LocalDateTime start = LocalDateTime.now().minusMinutes(30);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.IN_USE, OWNER_ID, start, end);
        Device d = device("IN_USE");
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);
        when(deviceMapper.selectById(DEVICE_ID)).thenReturn(d);

        // 非本人，但持有 device:approve（管理员代操作）
        SecurityUserDetails adminUd = udWithAuthorities(OTHER_ID,
                new SimpleGrantedAuthority("device:approve"));
        service.checkOut(RES_ID, adminUd);

        ArgumentCaptor<Reservation> rc = ArgumentCaptor.forClass(Reservation.class);
        verify(reservationMapper).updateById(rc.capture());
        assertEquals(ReservationStatus.COMPLETED.name(), rc.getValue().getStatus());
    }

    // ---------- checkOut ----------

    @Test
    void checkOut_in_use_succeeds() {
        LocalDateTime start = LocalDateTime.now().minusMinutes(30);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.IN_USE, OWNER_ID, start, end);
        Device d = device("IN_USE");
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);
        when(deviceMapper.selectById(DEVICE_ID)).thenReturn(d);

        service.checkOut(RES_ID, ownerUd(OWNER_ID));

        ArgumentCaptor<Reservation> rc = ArgumentCaptor.forClass(Reservation.class);
        verify(reservationMapper).updateById(rc.capture());
        assertEquals(ReservationStatus.COMPLETED.name(), rc.getValue().getStatus());
        assertNotNull(rc.getValue().getCheckOutAt());

        ArgumentCaptor<Device> dc = ArgumentCaptor.forClass(Device.class);
        verify(deviceMapper).updateById(dc.capture());
        assertEquals("IDLE", dc.getValue().getStatus());
        verify(itemMapper).delete(any());
    }

    @Test
    void checkOut_approved_rejected() {
        LocalDateTime start = LocalDateTime.now().minusMinutes(5);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID, start, end);
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.checkOut(RES_ID, ownerUd(OWNER_ID)));
        assertEquals(ResultCode.STATUS_TRANSITION_INVALID.getCode(), e.getCode());
    }

    @Test
    void checkOut_notOwner_noApprover_forbidden() {
        LocalDateTime start = LocalDateTime.now().minusMinutes(30);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.IN_USE, OWNER_ID, start, end);
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.checkOut(RES_ID, ownerUd(OTHER_ID)));
        assertEquals(ResultCode.FORBIDDEN.getCode(), e.getCode());
        verify(reservationMapper, never()).updateById(any());
    }

    // ---------- markViolated / markNoShow ----------

    @Test
    void markViolated_in_use_succeeds_and_releases_device() {
        LocalDateTime start = LocalDateTime.now().minusMinutes(10);
        LocalDateTime end = start.plusHours(1);
        Reservation r = reservation(ReservationStatus.IN_USE, OWNER_ID, start, end);
        Device d = device("IN_USE");
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);
        when(deviceMapper.selectById(DEVICE_ID)).thenReturn(d);

        service.markViolated(RES_ID);

        ArgumentCaptor<Reservation> rc = ArgumentCaptor.forClass(Reservation.class);
        verify(reservationMapper).updateById(rc.capture());
        assertEquals(ReservationStatus.VIOLATED.name(), rc.getValue().getStatus());

        ArgumentCaptor<Device> dc = ArgumentCaptor.forClass(Device.class);
        verify(deviceMapper).updateById(dc.capture());
        assertEquals("IDLE", dc.getValue().getStatus());
        verify(itemMapper).delete(any());
    }

    @Test
    void markViolated_pending_rejected() {
        Reservation r = reservation(ReservationStatus.PENDING, OWNER_ID,
                LocalDateTime.now().plusHours(1), LocalDateTime.now().plusHours(2));
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.markViolated(RES_ID));
        assertEquals(ResultCode.STATUS_TRANSITION_INVALID.getCode(), e.getCode());
    }

    @Test
    void markNoShow_approved_succeeds_and_releases() {
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID,
                LocalDateTime.now().minusHours(2), LocalDateTime.now().minusHours(1));
        Device d = device("IN_USE");
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);
        when(deviceMapper.selectById(DEVICE_ID)).thenReturn(d);

        service.markNoShow(RES_ID);

        ArgumentCaptor<Reservation> rc = ArgumentCaptor.forClass(Reservation.class);
        verify(reservationMapper).updateById(rc.capture());
        assertEquals(ReservationStatus.NO_SHOW.name(), rc.getValue().getStatus());
        verify(itemMapper).delete(any());
    }

    // ---------- not found ----------

    @Test
    void cancel_not_found_throws() {
        when(reservationMapper.selectById(RES_ID)).thenReturn(null);
        BusinessException e = assertThrows(BusinessException.class,
                () -> service.cancel(RES_ID, OWNER_ID));
        assertEquals(ResultCode.NOT_FOUND.getCode(), e.getCode());
    }

    // ---------- detail ----------

    @Test
    void detail_by_owner_succeeds() {
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID,
                LocalDateTime.now().plusHours(1), LocalDateTime.now().plusHours(2));
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        ReservationVO vo = service.detail(RES_ID, ownerUd(OWNER_ID));
        assertNotNull(vo);
        assertEquals(RES_ID, vo.getId());
        assertEquals(ReservationStatus.APPROVED.name(), vo.getStatus());
    }

    @Test
    void detail_by_non_owner_forbidden() {
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID,
                LocalDateTime.now().plusHours(1), LocalDateTime.now().plusHours(2));
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.detail(RES_ID, ownerUd(OTHER_ID)));
        assertEquals(ResultCode.FORBIDDEN.getCode(), e.getCode());
    }

    @Test
    void detail_by_approver_even_non_owner_succeeds() {
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID,
                LocalDateTime.now().plusHours(1), LocalDateTime.now().plusHours(2));
        when(reservationMapper.selectById(RES_ID)).thenReturn(r);

        // 持 device:approve 的管理员代查他人预约，应放行
        SecurityUserDetails admin = udWithAuthorities(OTHER_ID,
                new SimpleGrantedAuthority("device:approve"));
        ReservationVO vo = service.detail(RES_ID, admin);
        assertNotNull(vo);
        assertEquals(RES_ID, vo.getId());
    }

    // ---------- myReservations ----------

    @Test
    @SuppressWarnings("unchecked")
    void myReservations_filters_by_user_and_paginates() {
        // mock mapper.selectPage 返回一个含一条记录的 Page
        Reservation r = reservation(ReservationStatus.APPROVED, OWNER_ID,
                LocalDateTime.now().plusHours(1), LocalDateTime.now().plusHours(2));
        Page<Reservation> returned = new Page<>(1, 10);
        returned.setRecords(java.util.List.of(r));
        returned.setTotal(1);
        when(reservationMapper.selectPage(any(IPage.class), any(LambdaQueryWrapper.class)))
                .thenReturn(returned);

        IPage<ReservationVO> page = service.myReservations(OWNER_ID, null, 1, 10);
        assertNotNull(page);
        assertEquals(1, page.getTotal());
        assertEquals(1, page.getRecords().size());
        assertEquals(OWNER_ID, page.getRecords().get(0).getUserId());
    }
}
