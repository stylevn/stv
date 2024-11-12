-- CustomFluent.lua (Gộp tất cả trong một file)

local CustomFluent = {}

-- Khởi tạo cửa sổ
function CustomFluent:CreateWindow(title, size)
    local window = {}
    window.title = title or "New Window"
    window.size = size or {width = 300, height = 200}
    window.elements = {}

    -- Thêm nút vào cửa sổ
    function window:AddButton(text, onClick)
        local button = {}
        button.type = "button"
        button.text = text
        button.onClick = onClick
        table.insert(window.elements, button)
    end

    -- Thêm nhãn vào cửa sổ
    function window:AddLabel(text)
        local label = {}
        label.type = "label"
        label.text = text
        table.insert(window.elements, label)
    end

    -- Thêm ô nhập liệu vào cửa sổ
    function window:AddInput(placeholder)
        local input = {}
        input.type = "input"
        input.placeholder = placeholder or "Enter text"
        table.insert(window.elements, input)
    end

    -- Hiển thị cửa sổ và các thành phần bên trong
    function window:Show()
        print("Displaying window: " .. window.title)
        for _, element in ipairs(window.elements) do
            if element.type == "button" then
                print("Button: " .. element.text)
            elseif element.type == "label" then
                print("Label: " .. element.text)
            elseif element.type == "input" then
                print("Input: " .. element.placeholder)
            end
        end
    end

    return window
end

-- Ví dụ sử dụng thư viện CustomFluent

-- Tạo cửa sổ mới
local window = CustomFluent:CreateWindow("My Custom Window", {width = 400, height = 300})

-- Thêm các thành phần vào cửa sổ
window:AddLabel("This is a custom label")
window:AddButton("Click Me", function() print("Button clicked!") end)
window:AddInput("Type here")

-- Hiển thị cửa sổ
window:Show()

return CustomFluent