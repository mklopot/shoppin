<html>
<head>
    <meta http-equiv="refresh" content="1200">
    <script src="https://unpkg.com/htmx.org@1.9.6"></script>
    <script src="https://unpkg.com/hyperscript.org@0.9.14"></script>

<style>
body {
  font-family: Arial, Helvetica, sans-serif;
}

a:visited{
  color:blue;
}

a{
text-decoration: none
}

table, th, td {
  border: 1px dotted lightgray;
  border-collapse: collapse;
}
th, td {
  padding: 10px;
}
span.attribution{
  font-style: italic;
  font-size: 13px;
  color: gray;
}

.column {
  float: left;
  width: 50%;
}

.row:after {
  content: "";
  display: table;
  clear: both;
}

span.optional{
  color: gray;
}

a.x{
  opacity: 0.5;
  font-size: 0.8em;
  bottom: 0.3em;
  position: relative;
}

.greendot{
  opacity: 0.5;
  font-size: 0.8em;
}

.alreadyhave{
  text-align: center;
}


/***** MODAL DIALOG ****/
#modal {
	/* Underlay covers entire screen. */
	position: fixed;
	top:0px;
	bottom: 0px;
	left:0px;
	right:0px;
	background-color:rgba(0,0,0,0.5);
	z-index:1000;

	/* Flexbox centers the .modal-content vertically and horizontally */
	display:flex;
	flex-direction:column;
	align-items:center;

	/* Animate when opening */
	animation-name: fadeIn;
	animation-duration:150ms;
	animation-timing-function: ease;
}

#modal > .modal-underlay {
	/* underlay takes up the entire viewport. This is only
	required if you want to click to dismiss the popup */
	position: absolute;
	z-index: -1;
	top:0px;
	bottom:0px;
	left: 0px;
	right: 0px;
}

#modal > .modal-content {
        /* Added to try to make scrollable */
        overflow-y: auto;

	/* Position visible dialog near the top of the window */
	margin-top:10vh;

	/* Sizing for visible dialog */
	width:80%;
	max-width:600px;

	/* Display properties for visible dialog*/
	border:solid 1px #999;
	border-radius:8px;
	box-shadow: 0px 0px 20px 0px rgba(0,0,0,0.3);
	background-color:white;
	padding:20px;

	/* Animate when opening */
	animation-name:zoomIn;
	animation-duration:150ms;
	animation-timing-function: ease;
}

#modal.closing {
	/* Animate when closing */
	animation-name: fadeOut;
	animation-duration:150ms;
	animation-timing-function: ease;
}

#modal.closing > .modal-content {
	/* Animate when closing */
	animation-name: zoomOut;
	animation-duration:150ms;
	animation-timing-function: ease;
}

@keyframes fadeIn {
	0% {opacity: 0;}
	100% {opacity: 1;}
}

@keyframes fadeOut {
	0% {opacity: 1;}
	100% {opacity: 0;}
}

@keyframes zoomIn {
	0% {transform: scale(0.9);}
	100% {transform: scale(1);}
}

@keyframes zoomOut {
	0% {transform: scale(1);}
	100% {transform: scale(0.9);}
}

</style>

</head>
<body>
<div class="row">
  <div class="column">
    <a href="/add-recipe-to-database-form"><button>+ Add New Recipe to Database</button></a>
    <h1>Meal Plan</h1>
    % if mealplan:
      <h4>{{mealplan.name}}</h4>
      % for meal_index, meal in enumerate(mealplan.meals):
        <h3><span class="greendot">\\
        % if meal in meals_ready_to_cook:
         &#128994;\\
        % elif meal in meals_only_missing_optional:
         &#128993;\\
        % end
        </span> {{meal.name}}{{!meal.emoji}} <a class="x" href="/delete-meal/{{meal_index}}"> &#9447;</a></h3>
        <ul>
        % for recipe_index, recipe in enumerate(meal.recipes):
          <li><span class="greendot">\\
          % if  recipe in recipes_ready_to_cook:
         &#128994;\\
          % elif recipe in recipes_only_missing_optional:
         &#128993;\\
          % end
          </span> <a href="/recipe/{{recipe.id}}">{{recipe.name}}</a><a class="x" href="/delete-recipe-from-meal/{{meal_index}}/{{recipe_index}}"> &#9447;</a></li>


        % end
        <li><form hx-post="/add-dish" hx-target="body" hx-trigger="change">
            <input list="recipelist" name="recipe" placeholder="Add dish" required autocomplete="off">
            <input type="hidden" name="meal_index" value={{meal_index}}>
            <datalist id="recipelist">
            % for recipename in recipelist:
            <option value="{{recipename}}">
            % end
            </datalist>
            </form>
        </li>
        </ul>
      % end
      <form action="/add-meal" method="post">
      % if mealplan.meals:
      <input type="text" id="meal" name="meal">
      % else:
      <input type="text" id="meal" name="meal" placeholder="Meal name, like 'Monday Dinner'" required style="min-width: 300px">
      % end
      <input type="submit" value="+ Add New Meal"></form>
    % end 

    % if list_manager:
    <div>
    <h1>Include Preset Lists</h1>
    <form id="listmanager" action="/include-lists" method="post" 
                                _="on change
                                   if event.target.checked
                                     fetch `/modal/${event.target.id}` 
                                   then
                                     put it at end of the document.body
                                   else
                                     call me.submit()
                                   end">

    % for index, sublist in enumerate(list_manager.lists):
      % if sublist.include:
    <input type="checkbox" name={{index}} id="{{sublist.name}}" value="include" checked> {{sublist.name}}<a class="x" href="/edit-preset-list/{{sublist.name}}"> edit</a><br><br>
      % else:
    <input type="checkbox" name={{index}} id="{{sublist.name}}" value="include" > {{sublist.name}}<a class="x" href="/edit-preset-list/{{sublist.name}}"> edit</a><br><br>
      % end
    % end
    </form>

    <a href="/add-preset-list-form"> <button>+ Add new preset list</button></a>
    </div>
    % end
  </div>

  <div class="column">
  <h1>Shopping List </h1>
  <button hx-get="/clear" hx-target="body" hx-confirm="Are you sure you want to clear the Shopping List and the Meal Plan?">Clear Shopping List and Meal Plan</button>

    <div style="background-color: #C7F2FF">
    <h2>Add Item</h2>
    <form action="/add-item" method="POST">
    <input type="text" id="name" name="name" method="POST" placeholder='Name of item, like "celery"' required>
    <label for="name">Name</label><br>

    <input type="text" id="amount" name="amount" value="1" method="POST">
    <label for="amount">Amount</label><br>

    <input type="text" id="brand" name="brand" method="POST">
    <label for="brand">Brand <i>optional</i></label><br>

    <input type="text" id="vendor" name="vendor" method="POST">
    <label for="vendor">Best place to buy (King Soopers, etc) <i>optional</i></label><br>

    <input type="submit" value="+ Add Item" hx-boost="true"><br>
    </form>
    </div>
% if need:
  <h2>To Get</h2>
  % for category in need:
  <h4>{{category}}</h4>
  <table style="width:100%">
    % for item in need[category]:
  <tr>
     <td>{{item.name}}
         &nbsp;&nbsp;{{item.get_amount_with_unit()}}
         &nbsp;&nbsp;<span class="attribution">For {{item.get_purpose()}}</span>
      % if item.optional:
         <br>&nbsp;&nbsp;<span class="optional">optional</span>
      % end
      % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
      % end
      % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
      % end
      % if item.category == "other":
          <br><br>
          <form hx-post="/categorize" hx-trigger="change" hx-on="htmx:afterRequest:location.reload()"> 
            <input type="hidden" id="item" name="item" value="{{item.name}}"> 
            <label for="category" style="color: lightblue">set category: </label>
            <input list="categorylist" id="category" name="category" autocomplete="off" placeholder="category">
            <datalist id="categorylist">
            % for c in categories:
            <option value="{{c}}">
            % end
            </datalist>
          </form>
      % end
     </td>
     <td style="width:10%"><a href="/got/{{item.id}}" hx-boost="true" hx-swap='innerHTML show:no-scroll'><img src="images/cart3.svg" width="32" height="32"></a></td>
       % if not item.locked:
     <td style="width:10%"><a href="/have/{{item.id}}" hx-boost="true" hx-swap='innerHTML show:no-scroll'><img src="images/house-check-fill.svg" width="32" height="32"></a></td>
     <td style="width:10%"><a href="/lock/{{item.id}}" hx-boost="true" hx-swap='innerHTML show:no-scroll'><img src="images/house-dash.svg" width="32" height="32"></a></td>
       % end
    </tr>
  % end
  </table>
  % end
% end

% if got:
  <h2>Got</h2>
  <table style="width:100%; background-color:#f3f3f3">
  % for item in got:
  <tr>
     <td>{{item.name}}
         &nbsp;&nbsp;{{item.get_amount_with_unit()}}
         &nbsp;&nbsp;<span class="attribution">For {{item.get_purpose()}}</span>
    % if item.optional:
         <br>&nbsp;&nbsp;<span class="optional">optional</span>
    % end
    % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
    % end
    % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
    % end
     </td>
     <td style="width:10%">&#x2705;</td>
     <td style="width:20%"><a href="/need/{{item.id}}" hx-boost="true" hx-swap='innerHTML show:no-scroll'><img src="images/house-dash.svg" width="32" height="32"></a></td>
  </tr>
  % end
</table>
% end

% if have:
  <h2>Already Have</h2>
  <table style="width:100%; background-color:lightgray;">
  % for item in have:
  <tr>
     <td>{{item.name}}
         &nbsp;&nbsp;{{item.get_amount_with_unit()}}
         &nbsp;&nbsp;<span class="attribution">For {{item.get_purpose()}}</span>
    % if item.optional:
         <br>&nbsp;&nbsp;<span class="optional">optional</span>
    % end
    % if item.brand:
         <br>&nbsp;&nbsp;Brand: {{item.brand}}
    % end
    % if item.vendor:
         <br>&nbsp;&nbsp;Best Vendor: {{item.vendor}}
    % end
     </td>
     <td style="width:20%"><a href="/need/{{item.id}}" hx-boost="true" hx-swap='innerHTML show:no-scroll'><img src="images/house-dash.svg" width="32" height="32"></a></td>
  </tr>
  % end
</table>
% end

</div>
</div>
</body>
</html>
