package com.lab.reservation.ai.tool;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.DeviceCategoryService;
import com.lab.reservation.service.DeviceService;
import com.lab.reservation.vo.device.DeviceCategoryNodeVO;
import com.lab.reservation.vo.device.DeviceVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class DeviceToolTest {

    private DeviceService deviceService;
    private DeviceCategoryService categoryService;
    private ToolArgumentValidator validator;
    private DeviceTool deviceTool;

    @BeforeEach
    void setUp() {
        deviceService = mock(DeviceService.class);
        categoryService = mock(DeviceCategoryService.class);
        validator = new ToolArgumentValidator();
        deviceTool = new DeviceTool(deviceService, categoryService, validator);

        // 把 validator 规则注册到工具的 2 个方法上,模拟 ToolRegistry 启动行为
        try {
            validator.register("DeviceTool.searchDevices",
                    DeviceTool.class.getDeclaredMethod("searchDevices",
                            String.class, String.class, String.class, Integer.class));
            validator.register("DeviceTool.getDeviceDetails",
                    DeviceTool.class.getDeclaredMethod("getDeviceDetails", Long.class));
        } catch (NoSuchMethodException e) {
            throw new RuntimeException(e);
        }

        // 注入 SecurityContext(student1 / id=1)
        SecurityUserDetails user = new SecurityUserDetails(
                1L, "student1", "password", true, "学生1",
                List.of("STUDENT"), List.of());
        var auth = new UsernamePasswordAuthenticationToken(user, "password", user.getAuthorities());
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void searchDevices_calls_service_and_returns_result() {
        // given
        IPage<DeviceVO> page = new Page<>(1, 5);
        List<DeviceVO> records = new ArrayList<>();
        DeviceVO d1 = new DeviceVO();
        d1.setId(101L);
        d1.setName("示波器");
        DeviceVO d2 = new DeviceVO();
        d2.setId(102L);
        d2.setName("万用表");
        records.add(d1);
        records.add(d2);
        page.setRecords(records);
        page.setTotal(2L);

        when(categoryService.tree()).thenReturn(new ArrayList<>());
        when(deviceService.search(any())).thenReturn(page);

        // when
        ToolExecutionResult result = deviceTool.searchDevices("万用", null, null, 5);

        // then
        assertThat(result.isOk()).isTrue();
        assertThat(result.getData()).isInstanceOf(List.class);
        @SuppressWarnings("unchecked")
        List<DeviceVO> data = (List<DeviceVO>) result.getData();
        assertThat(data).hasSize(2);

        ArgumentCaptor<com.lab.reservation.dto.device.DeviceQueryDTO> captor =
                ArgumentCaptor.forClass(com.lab.reservation.dto.device.DeviceQueryDTO.class);
        verify(deviceService).search(captor.capture());
        assertThat(captor.getValue().getKeyword()).isEqualTo("万用");
        assertThat(captor.getValue().getSize()).isEqualTo(5L);
    }

    @Test
    void searchDevices_translates_category_name_to_id() {
        // given — category 树里有名为 "光学仪器" 的节点 id=7
        DeviceCategoryNodeVO node = new DeviceCategoryNodeVO();
        node.setId(7L);
        node.setName("光学仪器");
        List<DeviceCategoryNodeVO> tree = new ArrayList<>();
        tree.add(node);
        when(categoryService.tree()).thenReturn(tree);

        IPage<DeviceVO> page = new Page<>(1, 10);
        page.setRecords(new ArrayList<>());
        page.setTotal(0L);
        when(deviceService.search(any())).thenReturn(page);

        // when
        deviceTool.searchDevices(null, null, "光学仪器", 10);

        // then — service 收到 categoryId=7
        ArgumentCaptor<com.lab.reservation.dto.device.DeviceQueryDTO> captor =
                ArgumentCaptor.forClass(com.lab.reservation.dto.device.DeviceQueryDTO.class);
        verify(deviceService).search(captor.capture());
        assertThat(captor.getValue().getCategoryId()).isEqualTo(7L);
    }

    @Test
    void searchDevices_invalid_topN_returns_fail() {
        ToolExecutionResult r = deviceTool.searchDevices("k", null, null, 0);
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
    }

    @Test
    void getDeviceDetails_returns_device_from_service() {
        // given
        DeviceVO vo = new DeviceVO();
        vo.setId(42L);
        vo.setName("激光器");
        vo.setStatus("IDLE");
        when(deviceService.getById(42L)).thenReturn(vo);

        // when
        ToolExecutionResult result = deviceTool.getDeviceDetails(42L);

        // then
        assertThat(result.isOk()).isTrue();
        DeviceVO data = (DeviceVO) result.getData();
        assertThat(data.getId()).isEqualTo(42L);
        assertThat(data.getName()).isEqualTo("激光器");
        verify(deviceService).getById(42L);
    }

    @Test
    void getDeviceDetails_missing_id_throws_via_validator() {
        org.junit.jupiter.api.Assertions.assertThrows(
                com.lab.reservation.ai.exception.ToolArgumentException.class,
                () -> deviceTool.getDeviceDetails(null));
    }
}
