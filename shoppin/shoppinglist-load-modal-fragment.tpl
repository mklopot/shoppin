<div id="modal" _="on closeModal add .closing then wait for animationend then remove me">
	<div class="modal-underlay" _="on click trigger closeModal"></div>
	<div class="modal-content">
		<h1>Select items to load from preset list "{{preset_list.name}}"</h1>
                <form action="/load-preset-list-items" method="post">
                <input type="hidden" name="preset_list_name" value="{{preset_list.name}}">
                % for item in preset_list.items:
                <input type="checkbox" name="{{item.id}}" value="included" checked> {{item.name}}<br>
                % end
                <br>
                <button class="btn closemodal" _="on click trigger closeModal">Load</button>
                </form>
		<button class="btn cancelmodal" _="on click trigger closeModal then call window.location.reload()">Cancel</button>
	</div>
</div>
